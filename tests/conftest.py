# First, before anything imports the app: point AA_DATABASE_URL and the other path-like
# settings at a per-session temp directory (see _isolated_env.py and the SQLite guard below).
from _isolated_env import TEST_DATA_DIR

import asyncio
import ipaddress
import os
import re
import shlex
import sys
import tempfile
import warnings
from pathlib import Path
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
except ImportError as exc:  # a declared dependency: a move must not silently drop the stub
    raise ImportError(
        "network guard: claude_agent_sdk no longer provides "
        "claude_agent_sdk._internal.transport.subprocess_cli.SubprocessCLITransport. Update "
        "that import in tests/conftest.py to the SDK's CLI transport, so tests cannot spawn "
        "the `claude` CLI (which would fall back to the developer's keychain login)."
    ) from exc

try:
    from anthropic._base_client import BaseClient as _AnthropicBaseClient
except ImportError:  # pragma: no cover - only makes blocked calls fail fast, see below
    _AnthropicBaseClient = None

try:
    import uvloop
except ImportError:  # pragma: no cover - uvicorn[standard] ships it except on Windows
    uvloop = None

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
    "OPENROUTER_API_KEY",  # llm/keys.py: the OpenRouter backend's key
    "AA_LLM_BACKEND",  # llm/backends.py: "agent_sdk" or "openrouter" reroutes every call
    "AA_IN_CONTAINER",  # llm/backends.py: set by the Dockerfile; agent_sdk is refused there
    "ANTHROPIC_CUSTOM_HEADERS",  # Anthropic SDK: extra headers merged into every request
)

# Loopback is allowed, so a proxy listening on it would forward traffic out. Env-configured
# proxies are dropped for every guarded test, and NO_PROXY=* is set: a non-empty *_proxy env
# also stops urllib's getproxies() falling back to the OS proxy (macOS System Settings,
# Windows registry), which httpx and requests would otherwise use; both honour "*".
PROXY_ENV_VARS = tuple(
    name for base in ("http_proxy", "https_proxy", "all_proxy") for name in (base, base.upper()))
NO_PROXY_ENV_VARS = ("no_proxy", "NO_PROXY")

_LOOPBACK_NAMES = frozenset({"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"})

# Child processes are outside the audit hook's reach, so programs that reach the network by
# design are refused at spawn time (matched on the executable's basename). The suite's own
# children (sys.executable for alembic and the guard's inner pytest, `uv run --offline`, the
# POSIX shells running scripts/dev.sh) match none of these rules.
_NETWORK_PROGRAMS = frozenset({
    "claude", "node", "npx", "npm", "pnpm", "yarn", "bun", "deno", "curl", "wget",
    "ssh", "scp", "sftp", "rsync", "nc", "ncat", "telnet", "ftp", "gh", "docker",
})
_GIT_REMOTE_COMMANDS = frozenset({"clone", "fetch", "pull", "push", "ls-remote", "submodule"})
# `git remote` is local (-v, add, rename) except these, which contact the remote.
_GIT_REMOTE_NETWORK_SUBCOMMANDS = frozenset({"update", "show", "prune", "set-head"})
_GIT_VALUE_OPTIONS = frozenset({"-C", "-c", "--git-dir", "--work-tree", "--namespace",
                                "--exec-path", "--config-env"})
_PIP_PROGRAM = re.compile(r"pip(\d[\d.]*)?")  # pip, pip3, pip3.12
_PIP_NETWORK_COMMANDS = frozenset({"install", "download", "wheel"})
_SHELLS = frozenset({"sh", "bash", "dash", "zsh", "ksh"})
_SHELL_VALUE_OPTIONS = frozenset({"-o", "+o", "-O", "+O", "--rcfile", "--init-file"})
_SHELL_SEPARATORS = frozenset({"&&", "||", ";", "|", "&"})
_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
# Commands that run another command: (program) -> options that take a value. The wrapped
# command starts after the wrapper's options (and, for timeout, its duration).
_WRAPPERS = {
    "exec": frozenset({"-a"}),
    "command": frozenset(),
    "nohup": frozenset(),
    "env": frozenset({"-u", "--unset", "-C", "--chdir", "-S", "--split-string"}),
    "timeout": frozenset({"-s", "--signal", "-k", "--kill-after"}),
    "xargs": frozenset({"-a", "-d", "-E", "-e", "-I", "-i", "-L", "-l", "-n", "-P", "-s"}),
}
_SPAWN_EVENTS = frozenset({"subprocess.Popen", "os.posix_spawn", "os.exec", "os.spawn",
                           "os.system"})
_AUDIT_PREFIXES = ("socket.", "subprocess.", "os.")  # cheap pre-filter: hooks see every event
_UVLOOP_TARGET = ("uvloop event loop (its sockets bypass the audit hook, so the guard cannot "
                  "see them; use the default asyncio loop)")


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

    def record(self, target: str) -> None:
        self.attempts.setdefault(self.nodeid, []).append(target)

    def block(self, target: str) -> NoReturn:
        self.record(target)
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


def _program(path: object) -> str:
    name = os.path.basename(os.fsdecode(path)).lower()
    for suffix in (".exe", ".cmd", ".bat"):
        name = name.removesuffix(suffix)
    return name


def _env_flag(env: object, name: str) -> bool:
    source = env if hasattr(env, "get") else os.environ
    return str(source.get(name, "")).strip().lower() not in ("", "0", "false", "no")


def _with_assignments(env: object, assignments: list[str]) -> object:
    """The child's env after `VAR=val` words (a shell prefix or `env VAR=val`)."""
    if not assignments:
        return env
    merged = dict(env if hasattr(env, "items") else os.environ)
    merged.update(a.split("=", 1) for a in assignments)
    return merged


def _unwrap(argv: list[str], env: object) -> tuple[list[str], object]:
    """Strip leading `VAR=val` words and wrapper commands (exec, env, command, nohup,
    timeout N, xargs) down to the program that actually runs, tracking the env they set."""
    while argv:
        assignments = []
        while argv and _ASSIGNMENT.match(argv[0]):
            assignments.append(argv.pop(0))
        env = _with_assignments(env, assignments)
        if not argv or _program(argv[0]) not in _WRAPPERS:
            return argv, env
        wrapper, words = _program(argv[0]), argv[1:]
        if wrapper == "command" and {"-v", "-V"} & set(words):
            return [], env  # `command -v curl` looks curl up, it doesn't run it
        while words and words[0].startswith("-"):
            option = words.pop(0)
            if wrapper == "env" and option in ("-", "-i", "--ignore-environment"):
                env = {}
            elif option in _WRAPPERS[wrapper] and words:
                words.pop(0)  # the option's value
        if wrapper == "env":
            assignments = []
            while words and _ASSIGNMENT.match(words[0]):
                assignments.append(words.pop(0))
            env = _with_assignments(env, assignments)
        elif wrapper == "timeout" and words:
            words.pop(0)  # the duration
        argv = words
    return argv, env


def _shell_command_string(rest: list[str]) -> str | None:
    """The string a shell runs with -c (`-c`, `-lc`, `-e -c`, ...); None for a script."""
    has_c, words = False, iter(rest)
    for word in words:
        if word == "--":
            break
        if word in _SHELL_VALUE_OPTIONS:
            next(words, None)
        elif word.startswith("-") and not word.startswith("--") and len(word) > 1:
            has_c = has_c or "c" in word[1:]
        elif not word.startswith(("--", "+")):
            return word if has_c else None
    return next(words, None) if has_c else None


def _shell_network_command(command: object, env: object) -> str | None:
    """The first network-capable command in a `sh -c` / os.system string, if any.

    Only simple commands joined by spaced operators (`a && b`, `a; b`, `a | b`) are seen.
    Command substitution (`$(curl x)`, backticks), subshells and groups (`(curl x)`,
    `{ curl x; }`), unspaced operators (`a&&curl x`), functions, aliases and scripts the
    string sources are out of reach: they would need a shell parser."""
    try:
        words = shlex.split(os.fsdecode(command))
    except ValueError:
        return None
    argv: list[str] = []
    for word in [*words, ";"]:
        if word not in _SHELL_SEPARATORS:
            argv.append(word)
        elif argv:
            if reason := _network_command(argv, env):
                return reason
            argv = []
    return None


def _network_command(argv: list, env: object) -> str | None:
    """Why spawning argv would reach the network, or None for a local command. `env` is the
    child's environment (None: inherits this process's)."""
    argv, env = _unwrap([os.fsdecode(a) for a in argv], env)
    if not argv:
        return None
    program, rest = _program(argv[0]), argv[1:]
    if program in _SHELLS:
        command = _shell_command_string(rest)
        return _shell_network_command(command, env) if command is not None else None
    if program in _NETWORK_PROGRAMS:
        return program
    if program == "git":
        words = iter(rest)
        subcommand = ""
        for word in words:
            if word in _GIT_VALUE_OPTIONS:
                next(words, None)  # `git -C path clone ...`: skip the option's value
            elif not word.startswith("-"):
                subcommand = word
                break
        if subcommand == "remote":
            action = next((w for w in words if not w.startswith("-")), "")
            return f"git remote {action}" if action in _GIT_REMOTE_NETWORK_SUBCOMMANDS else None
        return f"git {subcommand}" if subcommand in _GIT_REMOTE_COMMANDS else None
    if program in ("uv", "uvx"):
        offline = "--offline" in rest or _env_flag(env, "UV_OFFLINE")
        return None if offline else f"{program} without --offline"
    is_pip = _PIP_PROGRAM.fullmatch(program) is not None or (
        program.startswith("python") and "-m" in rest
        and rest[rest.index("-m") + 1:rest.index("-m") + 2] == ["pip"])
    if is_pip and _PIP_NETWORK_COMMANDS & set(rest):
        return "pip install"
    return None


def _spawn_argv(event: str, args: tuple) -> tuple[list, object] | None:
    """(argv, env) from a process-spawn audit event.

    Out of reach (CI is Linux): on Windows, Popen's audit argv is one command-line string,
    so only its first word is classified; on POSIX, os.spawn* is fork + exec, so its
    "os.exec" block fires in the forked child, where the error cannot reach the caller."""
    if event == "subprocess.Popen":
        executable, argv, _cwd, env = args
        argv = list(argv) if isinstance(argv, list | tuple) else [argv]
        return [executable or argv[0], *argv[1:]], env
    if event in ("os.posix_spawn", "os.exec"):
        path, argv, env = args
        return [path, *list(argv)[1:]], env
    if event == "os.spawn":
        _mode, path, argv, env = args
        return [path, *list(argv)[1:]], env
    return None


def _network_audit_hook(event: str, args: tuple) -> None:
    """Block at the socket layer, below every client library. CPython raises these audit
    events from C before any packet leaves, whatever imported `socket` how (`from socket
    import create_connection` included), and in every thread. In-process traffic never
    reaches a socket (TestClient is an httpx client on an in-process ASGI transport), and
    loopback and Unix-domain sockets pass, so local servers and asyncio's self-pipe work.
    Spawning a network-capable program is refused here too (subprocess, os.posix_spawn,
    os.exec*, os.spawn*, os.system), since a child process's own sockets are invisible."""
    if _GUARD.allowed or not event.startswith(_AUDIT_PREFIXES):
        return
    if event in ("socket.getaddrinfo", "socket.gethostbyname"):
        # A name lookup asks a resolver, so it is outbound even if no connection follows.
        # A numeric address needs no lookup; its connect is checked below.
        host = args[0]
        if not _is_loopback(host) and _numeric_ip(_host_text(host)) is None:
            _GUARD.block(_target(host, args[1] if len(args) > 1 else None))
    elif event in ("socket.gethostbyaddr", "socket.getnameinfo"):
        # A reverse lookup sends a PTR query even for a numeric address.
        host = args[0][0] if isinstance(args[0], tuple) else args[0]
        if not _is_loopback(host):
            _GUARD.block(f"{_host_text(host)} (reverse lookup)")
    elif event in ("socket.connect", "socket.sendto", "socket.sendmsg"):
        address = args[1]
        if (isinstance(address, tuple) and address
                and isinstance(address[0], str | bytes) and not _is_loopback(address[0])):
            _GUARD.block(_target(address[0], address[1] if len(address) > 1 else None))
    elif event in _SPAWN_EVENTS:
        if event == "os.system":
            reason = _shell_network_command(args[0], None)
        else:
            argv, env = _spawn_argv(event, args) or ([], None)
            reason = _network_command(argv, env)
        if reason:
            _GUARD.block(f"child process {reason}")


sys.addaudithook(_network_audit_hook)  # audit hooks cannot be removed; the guard gates it


def _uvloop_policy_active() -> bool:
    # Loop policies are deprecated in 3.14 and removed in 3.16; without them uvloop can only
    # arrive through a loop factory, which `_no_real_network` blocks.
    get_policy = getattr(asyncio, "get_event_loop_policy", None)
    if get_policy is None:
        return False
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        policy = get_policy()
    return type(policy).__module__.split(".")[0] == "uvloop"


def _blocked_message(nodeid: str, targets: list[str]) -> str:
    return (
        f"{nodeid} tried to reach the network: {', '.join(dict.fromkeys(targets))}\n"
        "The attempt was blocked, but the code under test may have caught the error and "
        "degraded gracefully, so the test body alone cannot be trusted to notice.\n"
        "Fix: run LLM calls through the scripted client (adaptive_academy.llm.scripted_client) "
        "or a fake, or monkeypatch the call site (fetcher, resolver, embedder, SDK query, "
        "subprocess) with a stub. Only a test that deliberately exercises a guarded path with "
        "its own stub may opt out with @pytest.mark.allow_network."
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
    if call.when in ("call", "teardown") and not _GUARD.allowed and _uvloop_policy_active():
        _GUARD.record(_UVLOOP_TARGET)
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


def _caused_by_block(err: BaseException | None) -> bool:
    seen: set[int] = set()
    while err is not None and id(err) not in seen:
        if isinstance(err, NetworkBlockedError):
            return True
        seen.add(id(err))
        err = err.__cause__ or err.__context__
    return False


@pytest.fixture(autouse=True)
def _no_real_network(request, monkeypatch):
    """No test reaches a real outside service; each attempt fails the test that made it.

    Real sockets are blocked process-wide by `_network_audit_hook`: forward and reverse name
    lookups and connections to any non-loopback host raise NetworkBlockedError (the Anthropic
    SDK's HTTP transport, the SSRF-guarded fetch in engine/fetch.py and a fastembed model
    download all end there), and so does spawning a network-capable program (claude, node,
    curl, git clone, uv without --offline, pip install, ...). TestClient keeps working
    (in-process, no socket), as do loopback servers and the suite's own child processes.

    This fixture adds what the hook cannot see: it stubs the Agent SDK's CLI transport, so
    `claude_agent_sdk.query()` and `ClaudeSDKClient` cannot spawn the `claude` subprocess
    (tests that fake `query` at its call site are unaffected); it blocks uvloop, whose
    sockets raise no audit events (a uvloop policy left in place also fails the test); and it
    drops proxy env vars and sets NO_PROXY=* so neither an env nor an OS proxy on loopback
    can carry traffic past the hook. A blocked Anthropic call fails at once instead of
    sleeping through its retries.

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
    for name in NO_PROXY_ENV_VARS:
        monkeypatch.setenv(name, "*")

    async def _blocked_connect(self):
        _GUARD.block("claude CLI subprocess (claude_agent_sdk transport)")

    monkeypatch.setattr(SubprocessCLITransport, "connect", _blocked_connect)

    if uvloop is not None:
        def _blocked_uvloop(*args, **kwargs):
            for arg in args:  # uvloop.run(coro): don't leave the coroutine un-awaited
                if asyncio.iscoroutine(arg):
                    arg.close()
            _GUARD.block(_UVLOOP_TARGET)

        for name in ("new_event_loop", "run", "install"):
            if hasattr(uvloop, name):
                monkeypatch.setattr(uvloop, name, _blocked_uvloop)

    if _AnthropicBaseClient is not None and hasattr(_AnthropicBaseClient,
                                                    "_should_retry_exception"):
        should_retry = _AnthropicBaseClient._should_retry_exception

        def _no_retry_when_blocked(self, err):
            return (False, None) if _caused_by_block(err) else should_retry(self, err)

        monkeypatch.setattr(_AnthropicBaseClient, "_should_retry_exception",
                            _no_retry_when_blocked)


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


# --- Database guard --------------------------------------------------------------------------
# _isolated_env.py points AA_DATABASE_URL (and the other path-like settings) at a per-session
# temp directory before the app is imported, so settings, db.engine, the usage recorder's
# default bind, backup/export and alembic/env.py all resolve there. This guard backs that up
# at runtime: a SQLite connection to any database FILE outside the temp directory (the
# developer's adaptive_academy.db, a backups/ dir in the repo, anything under $HOME) is
# blocked before sqlite opens or creates the file, and fails the test that tried, even if the
# code under test caught the error. In-memory databases and tmp_path files are unaffected.

_TEMP_ROOTS = tuple(dict.fromkeys((Path(tempfile.gettempdir()).resolve(), TEST_DATA_DIR)))


class RealDatabaseBlockedError(PermissionError):
    """Raised in place of opening a SQLite file outside the temp directory during tests."""


def sqlite_file_target(database: object) -> Path | None:
    """The file a `sqlite3.connect(database)` call would open, or None for an in-memory db."""
    text = os.fsdecode(database) if isinstance(database, bytes | os.PathLike) else str(database)
    if text in ("", ":memory:"):
        return None
    if text.startswith("file:"):  # URI filename (uri=True): file:path?mode=...
        path, _, query = text[len("file:"):].partition("?")
        if path.startswith("//"):  # file://host/path; sqlite accepts only an empty host
            path = "/" + path[2:].partition("/")[2]
        if "mode=memory" in query or path in ("", ":memory:"):
            return None
        text = path
    return Path(text).expanduser().resolve()


def sqlite_file_allowed(path: Path) -> bool:
    return (any(path.is_relative_to(root) for root in _TEMP_ROOTS)
            or path.name.startswith(".coverage"))  # coverage.py's own data file


class _DatabaseGuard:
    def __init__(self) -> None:
        self.attempts: dict[str | None, list[str]] = {}


_DB_GUARD = _DatabaseGuard()


def _sqlite_audit_hook(event: str, args: tuple) -> None:
    if event != "sqlite3.connect" or not args:
        return
    target = sqlite_file_target(args[0])
    if target is None or sqlite_file_allowed(target):
        return
    _DB_GUARD.attempts.setdefault(_GUARD.nodeid, []).append(str(target))
    raise RealDatabaseBlockedError(
        f"tests may only open SQLite files under the temp directory, not {target}")


sys.addaudithook(_sqlite_audit_hook)


@pytest.fixture(autouse=True)
def _no_real_database(request):
    """Fail the test if anything in it tried to open a SQLite file outside the temp dir."""
    yield
    targets = _DB_GUARD.attempts.pop(request.node.nodeid, None)
    if targets:
        pytest.fail(
            f"{request.node.nodeid} tried to open a database outside the temp directory: "
            f"{', '.join(dict.fromkeys(targets))}\nUse the `session` fixture or a tmp_path "
            "file; the real database is never a test target.", pytrace=False)


@pytest.fixture(autouse=True, scope="session")
def _no_real_database_outside_tests():
    yield
    stray = _DB_GUARD.attempts.pop(None, None)
    if stray:
        pytest.fail("a database outside the temp directory was opened outside any test: "
                    f"{', '.join(dict.fromkeys(stray))}", pytrace=False)
