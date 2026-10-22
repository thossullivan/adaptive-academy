import ipaddress
import sys
from typing import NoReturn

import pytest
from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from adaptive_academy.api import deps as api_deps
from adaptive_academy.db import ensure_fts
from adaptive_academy.llm import usage as llm_usage

try:  # The Agent SDK (subscription backend) spawns the `claude` CLI from this transport.
    from claude_agent_sdk._internal.transport.subprocess_cli import SubprocessCLITransport
except ImportError:  # pragma: no cover - the SDK is a declared dependency
    SubprocessCLITransport = None

# --- Network guard ---------------------------------------------------------------------------
# The app degrades gracefully: a failed model call, fetch or embedder download is caught and
# turned into a fallback. So a test that accidentally reaches a real service can pass while
# spending money or leaking data. The guard blocks every such attempt AND records it, and the
# test fails at teardown whether or not the code under test swallowed the error.

# Credentials and endpoints that would route a test to a real provider. `just test` loads
# the developer's .env into the environment (justfile: dotenv-load), so these are scrubbed for
# every test; a test that needs "a key is configured" sets a fake one with monkeypatch.
PROVIDER_ENV_VARS = (
    "ANTHROPIC_API_KEY",  # llm/keys.py and the Anthropic SDK
    "ANTHROPIC_AUTH_TOKEN",  # Anthropic SDK bearer-token auth
    "ANTHROPIC_BASE_URL",  # Anthropic SDK endpoint override
    "CLAUDE_CODE_OAUTH_TOKEN",  # Agent SDK subscription token for the `claude` CLI
    "AA_LLM_BACKEND",  # api/deps.py: "agent_sdk" routes every call to the subscription
)

# Loopback is allowed, so a proxy listening on it would forward traffic out. Env-configured
# proxies are dropped for every guarded test; httpx and urllib then connect directly.
PROXY_ENV_VARS = tuple(
    name for base in ("http_proxy", "https_proxy", "all_proxy") for name in (base, base.upper()))

_LOOPBACK_NAMES = frozenset({"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"})


class NetworkBlockedError(ConnectionError):
    """Raised in place of a real outbound connection during a test. An OSError subclass, so
    callers see what they would see offline (httpx maps it to ConnectError)."""


class _NetworkGuard:
    """Process-wide state behind the audit hook. pytest runs one test at a time per process,
    so the current test is plain state, set around each test's whole run protocol (setup,
    call, teardown) by `pytest_runtest_protocol`. Attempts outside any test key on None."""

    def __init__(self) -> None:
        self.nodeid: str | None = None
        self.allowed = False
        self.attempts: dict[str | None, list[str]] = {}

    def block(self, target: str) -> NoReturn:
        self.attempts.setdefault(self.nodeid, []).append(target)
        raise NetworkBlockedError(f"network access is blocked in tests: {target}")


_GUARD = _NetworkGuard()


def _host_text(host: object) -> str:
    if isinstance(host, bytes | bytearray):
        host = bytes(host).decode("ascii", "replace")
    return str(host).strip().lower().rstrip(".")


def _numeric_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        ip = ipaddress.ip_address(host.strip("[]").split("%", 1)[0])
    except ValueError:
        return None
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    return ip


def _is_loopback(host: object) -> bool:
    if host is None:  # getaddrinfo(None, port) is the local wildcard, no lookup
        return True
    text = _host_text(host)
    if not text or text in _LOOPBACK_NAMES:
        return True
    ip = _numeric_ip(text)
    return ip is not None and ip.is_loopback


def _target(host: object, port: object) -> str:
    return f"{_host_text(host)}:{port}" if port not in (None, 0, "") else _host_text(host)


def _network_audit_hook(event: str, args: tuple) -> None:
    """Block at the socket layer, below every client library. CPython raises these audit
    events from C before any packet leaves, whatever imported `socket` how (`from socket
    import create_connection` included), and in every thread. In-process traffic never
    reaches a socket (TestClient is an httpx client on an in-process ASGI transport), and
    loopback and Unix-domain sockets pass, so local servers and asyncio's self-pipe work."""
    if _GUARD.allowed or not event.startswith("socket."):
        return
    if event in ("socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr"):
        # A name lookup asks a resolver, so it is outbound even if no connection follows.
        # A numeric address needs no lookup; its connect is checked below.
        host = args[0]
        if not _is_loopback(host) and _numeric_ip(_host_text(host)) is None:
            _GUARD.block(_target(host, args[1] if len(args) > 1 else None))
    elif event in ("socket.connect", "socket.sendto", "socket.sendmsg"):
        address = args[1]
        if (isinstance(address, tuple) and address
                and isinstance(address[0], str | bytes) and not _is_loopback(address[0])):
            _GUARD.block(_target(address[0], address[1] if len(address) > 1 else None))


sys.addaudithook(_network_audit_hook)  # audit hooks cannot be removed; the guard gates it


def _blocked_message(nodeid: str, targets: list[str]) -> str:
    return (
        f"{nodeid} tried to reach the network: {', '.join(dict.fromkeys(targets))}\n"
        "The attempt was blocked, but the code under test may have caught the error and "
        "degraded gracefully, so the test body alone cannot be trusted to notice.\n"
        "Fix: run LLM calls through the scripted client (adaptive_academy.llm.scripted_client) "
        "or a fake, or monkeypatch the call site (fetcher, resolver, embedder, SDK query) "
        "with a stub. Only a test that deliberately exercises a guarded path with its own "
        "stub may opt out with @pytest.mark.allow_network."
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "allow_network: opt out of the network guard, for a test that deliberately "
        "exercises a guarded path with its own stub (see _no_real_network in conftest.py)",
    )


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_runtest_protocol(item, nextitem):
    _GUARD.nodeid = item.nodeid
    _GUARD.allowed = item.get_closest_marker("allow_network") is not None
    try:
        return (yield)
    finally:
        _GUARD.nodeid, _GUARD.allowed = None, False


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    report = yield
    if call.when == "teardown":
        targets = _GUARD.attempts.pop(item.nodeid, None)
        if targets:
            message = _blocked_message(item.nodeid, targets)
            if report.failed:
                report.sections.append(("network guard", message))
            else:
                report.outcome = "failed"
                report.longrepr = message
    return report


def pytest_sessionfinish(session, exitstatus):
    stray = _GUARD.attempts.pop(None, None)
    if stray:  # e.g. at import or collection time, outside every test's protocol
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        if reporter is not None:
            reporter.write_line(_blocked_message("(outside any test)", stray), red=True)


@pytest.fixture(autouse=True)
def _no_real_network(request, monkeypatch):
    """No test reaches a real outside service; each attempt fails the test that made it.

    Real sockets are blocked process-wide by `_network_audit_hook`: name lookups and
    connections to any non-loopback host raise NetworkBlockedError (the Anthropic SDK's HTTP
    transport, the SSRF-guarded fetch in engine/fetch.py and a fastembed model download all
    end there). TestClient keeps working (in-process, no socket), as do loopback servers.
    This fixture also stubs the Agent SDK's CLI transport, so `claude_agent_sdk.query()` and
    `ClaudeSDKClient` cannot spawn the `claude` subprocess, whose own traffic the in-process
    hook could not see. Tests that fake `query` at its call site are unaffected. Proxy env
    vars are dropped too, since a proxy on loopback would carry traffic past the hook.

    Every attempt is recorded against the running test, and `pytest_runtest_makereport`
    fails that test at teardown, naming the host, even when the code under test caught the
    error and degraded gracefully. Attempts during any phase (fixture setup, the call,
    fixture teardown) count, and are attributed to the test whose protocol was running.

    Opt-out: `@pytest.mark.allow_network` disables the guard for one test. Reserve it for a
    test that deliberately drives a guarded path with its own stub; never use it to make a
    test that really reached the network pass. Credentials stay scrubbed regardless."""
    if request.node.get_closest_marker("allow_network"):
        return
    for name in PROXY_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    if SubprocessCLITransport is None:
        return

    async def _blocked_connect(self):
        _GUARD.block("claude CLI subprocess (claude_agent_sdk transport)")

    monkeypatch.setattr(SubprocessCLITransport, "connect", _blocked_connect)


@pytest.fixture(autouse=True)
def _no_provider_env(monkeypatch):
    """No provider credential or backend switch leaks in from the developer's environment
    (`just test` loads .env). A test that needs "a key is configured" sets a fake one with
    monkeypatch.setenv; one that needs agent_sdk mode sets AA_LLM_BACKEND itself."""
    for name in PROVIDER_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _block_live_source_fetch(monkeypatch):
    """Keep route tests offline unless they explicitly override the fetch dependency."""
    monkeypatch.setattr(api_deps, "fetch_artifact_text", lambda _: None)


@pytest.fixture(autouse=True)
def _offline_retriever(monkeypatch):
    """Route tests never construct the live embedder: the default retriever is scripted and
    model downloads are disabled for the whole test process. Tests that want the hybrid
    path build it explicitly with ScriptedEmbedder."""
    monkeypatch.setattr(api_deps.settings, "retriever", "scripted")
    monkeypatch.setattr(api_deps.settings, "embedding_allow_download", False)
    api_deps.reset_retriever_cache()
    yield
    api_deps.reset_retriever_cache()


@pytest.fixture(autouse=True)
def _usage_bind_off(monkeypatch):
    """LLM usage rows go to the `session` fixture's in-memory engine when a test uses it,
    and nowhere otherwise — a test must never write usage into the real database file. No
    daily spending limit either, whatever the developer's .env says."""
    llm_usage.set_usage_bind(None)
    monkeypatch.setattr(llm_usage.settings, "daily_budget_usd", None)
    yield
    llm_usage.reset_usage_bind()


@pytest.fixture
def session(_usage_bind_off):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    SQLModel.metadata.create_all(engine)
    ensure_fts(engine)
    llm_usage.set_usage_bind(engine)
    with Session(engine) as s:
        yield s
