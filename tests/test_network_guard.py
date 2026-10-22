"""The conftest network guard fails a test that reaches a real outside service, even when the
code under test swallows the error, and leaves in-process and loopback traffic alone.

The guard's own behaviour is checked by running a small inner suite under a copy of this
conftest in a separate pytest process: the audit hook it installs is process-wide
and permanent, so an in-process inner run would also trip the outer test's guard. Nothing
here sends a packet: every real attempt is blocked before DNS or connect, and the targets are
reserved names and documentation addresses (RFC 2606 / RFC 5737) in case the guard broke.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import PROVIDER_ENV_VARS

CONFTEST = Path(__file__).with_name("conftest.py")

INNER_TESTS = '''
import asyncio
import os
import socket
import subprocess
import sys
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_swallowed_lookup():
    try:
        socket.create_connection(("guard-probe.example.invalid", 443), timeout=1)
    except OSError:
        pass  # graceful degradation: the body alone would pass


def test_swallowed_connect_to_address():
    try:
        socket.create_connection(("192.0.2.1", 443), timeout=1)
    except OSError:
        pass


def test_anthropic_sdk_transport_is_blocked():
    import anthropic

    # Default max_retries: a blocked call must fail at once, not sleep through the backoff
    # (at least ~1.1 s for two retries).
    client = anthropic.Anthropic(api_key="sk-ant-test-not-a-real-key")
    started = time.monotonic()
    with pytest.raises(anthropic.APIConnectionError):
        client.messages.create(model="claude-haiku-5-5", max_tokens=1,
                               messages=[{"role": "user", "content": "hi"}])
    assert time.monotonic() - started < 0.5


def test_os_proxy_on_loopback_is_not_used(monkeypatch):
    import urllib.request

    import anthropic

    with socket.socket() as listener:  # stands in for ClashX / Proxyman / Charles
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.setblocking(False)
        proxy = f"http://127.0.0.1:{listener.getsockname()[1]}"
        for name in ("getproxies_macosx_sysconf", "getproxies_registry"):  # OS fallbacks
            if hasattr(urllib.request, name):
                monkeypatch.setattr(urllib.request, name, lambda: {"http": proxy, "https": proxy})
        assert proxy not in urllib.request.getproxies().values()
        client = anthropic.Anthropic(api_key="sk-ant-test-not-a-real-key", max_retries=0,
                                     timeout=2)
        with pytest.raises(anthropic.APIConnectionError):
            client.messages.create(model="claude-haiku-5-5", max_tokens=1,
                                   messages=[{"role": "user", "content": "hi"}])
        with pytest.raises(BlockingIOError):
            listener.accept()  # nothing ever connected to the "proxy"


def test_swallowed_reverse_lookups():
    for lookup in (lambda: socket.gethostbyaddr("192.0.2.7"),
                   lambda: socket.getnameinfo(("192.0.2.8", 443), 0)):
        try:
            lookup()
        except OSError:
            pass


def test_network_child_processes_are_blocked():
    # Nonexistent paths: were the guard broken, each spawn would fail with FileNotFoundError
    # instead of running anything. The pip install is --no-index for the same reason.
    attempts = [
        lambda: subprocess.run(["/nonexistent/curl", "https://guard-probe.example.invalid"]),
        lambda: subprocess.run(["/nonexistent/git", "-C", ".", "clone", "https://x.invalid/r"]),
        lambda: subprocess.run(["/nonexistent/uv", "sync"]),
        lambda: subprocess.run([sys.executable, "-m", "pip", "install", "--no-index", "nope"],
                               capture_output=True),
        lambda: subprocess.run("/nonexistent/wget https://guard-probe.example.invalid",
                               shell=True),
        lambda: os.system("cd . && /nonexistent/npx some-tool"),
        lambda: os.posix_spawn("/nonexistent/node", ["node", "-e", "1"], os.environ),
        lambda: os.execv("/nonexistent/claude", ["claude", "-p", "hi"]),
    ]
    for attempt in attempts:
        try:
            attempt()
        except OSError:
            pass


def test_local_child_processes_still_run():
    assert subprocess.run([sys.executable, "-c", "pass"]).returncode == 0
    # Allowed commands reach the OS: a missing binary fails as FileNotFoundError, not blocked.
    for argv in (["/nonexistent/uv", "run", "--offline", "alembic", "upgrade", "head"],
                 ["/nonexistent/git", "status"],
                 ["/nonexistent/sh", "scripts/dev.sh"]):
        with pytest.raises(FileNotFoundError):
            subprocess.run(argv)


def test_uvloop_run_is_blocked():
    import uvloop

    async def main():
        return 1

    try:
        uvloop.run(main())
    except OSError:
        pass


@pytest.fixture
def restore_loop_policy():
    policy = asyncio.get_event_loop_policy()
    yield
    asyncio.set_event_loop_policy(policy)


def test_uvloop_policy_fails_the_test(restore_loop_policy):
    import uvloop

    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())


def test_agent_sdk_query_is_blocked():
    from claude_agent_sdk import query

    async def run():
        async for _ in query(prompt="hi"):
            pass

    try:
        asyncio.run(run())
    except Exception:
        pass


@pytest.fixture
def leaks_in_teardown():
    yield
    try:
        socket.getaddrinfo("teardown-probe.example.invalid", 443)
    except OSError:
        pass


def test_attempt_in_fixture_teardown(leaks_in_teardown):
    pass


def test_clean_after_a_blocked_test():
    pass


def test_testclient_still_works():
    app = FastAPI()

    @app.get("/ping")
    def ping():
        return {"ok": True}

    assert TestClient(app).get("/ping").json() == {"ok": True}


def test_loopback_still_works():
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        with socket.create_connection(server.getsockname(), timeout=1):
            pass
        with socket.create_connection(("localhost", server.getsockname()[1]), timeout=1):
            pass
    socket.getnameinfo(("127.0.0.1", 80), socket.NI_NUMERICHOST)


def test_provider_credentials_are_scrubbed():
    import os

    assert "ANTHROPIC_API_KEY" not in os.environ
    assert "AA_LLM_BACKEND" not in os.environ


@pytest.mark.allow_network
def test_marker_opts_out():
    # sys.audit raises the same event a real connect would, without touching a socket.
    sys.audit("socket.connect", None, ("192.0.2.1", 443))
'''


@pytest.fixture(scope="module")
def result(tmp_path_factory) -> subprocess.CompletedProcess[str]:
    inner = tmp_path_factory.mktemp("network_guard")
    (inner / "conftest.py").write_text(CONFTEST.read_text())
    (inner / "test_inner.py").write_text(INNER_TESTS)
    # Module fixtures run before the function-scoped env scrub, so build the child's env
    # explicitly: no real credential leaves this process. The fake key and backend switch
    # check that the inner conftest scrubs them per test even when they are set.
    env = {k: v for k, v in os.environ.items() if k not in PROVIDER_ENV_VARS}
    env.update(ANTHROPIC_API_KEY="sk-ant-test-not-a-real-key", AA_LLM_BACKEND="agent_sdk")
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-rA", str(inner)],
        cwd=inner, env=env, capture_output=True, text=True, timeout=120, check=False,
    )


def _summary(result, name: str) -> list[str]:
    """The inner run's short-summary lines (-rA) for one test: "PASSED ...", "ERROR ..."."""
    return [line.split(" ", 1)[0] for line in result.stdout.splitlines()
            if line.split(" ", 1)[0] in ("PASSED", "FAILED", "ERROR")
            and f"test_inner.py::{name}" in line.split(" - ", 1)[0].split()]


BLOCKED = {
    "test_swallowed_lookup": ["guard-probe.example.invalid:443"],
    "test_swallowed_connect_to_address": ["192.0.2.1:443"],
    "test_anthropic_sdk_transport_is_blocked": ["api.anthropic.com:443"],
    "test_os_proxy_on_loopback_is_not_used": ["api.anthropic.com:443"],
    "test_agent_sdk_query_is_blocked": ["claude CLI subprocess"],
    "test_attempt_in_fixture_teardown": ["teardown-probe.example.invalid:443"],
    "test_swallowed_reverse_lookups": ["192.0.2.7 (reverse lookup)",
                                       "192.0.2.8 (reverse lookup)"],
    "test_network_child_processes_are_blocked": [
        "child process curl", "child process git clone", "child process uv without --offline",
        "child process pip install", "child process wget", "child process npx",
        "child process node", "child process claude"],
    "test_uvloop_run_is_blocked": ["uvloop event loop"],
    "test_uvloop_policy_fails_the_test": ["uvloop event loop"],
}
PASSING = [
    "test_clean_after_a_blocked_test",
    "test_testclient_still_works",
    "test_loopback_still_works",
    "test_provider_credentials_are_scrubbed",
    "test_marker_opts_out",
    "test_local_child_processes_still_run",
]


def _message(result, name: str) -> str:
    prefix = f"test_inner.py::{name} tried to reach the network: "
    return next((line for line in result.stdout.splitlines() if line.startswith(prefix)), "")


@pytest.mark.parametrize("name,targets", BLOCKED.items(), ids=list(BLOCKED))
def test_swallowed_real_connection_fails_the_test_that_made_it(result, name, targets):
    message = _message(result, name)
    assert all(target in message for target in targets), message or result.stdout
    # The body passed (the error was swallowed or expected); the guard fails it at teardown.
    assert _summary(result, name) == ["PASSED", "ERROR"], result.stdout
    assert "scripted client" in result.stdout


def test_failure_is_attributed_only_to_the_offending_tests(result):
    assert result.returncode == 1, result.stdout + result.stderr
    totals = result.stdout.splitlines()[-1]
    passed, errors = len(BLOCKED) + len(PASSING), len(BLOCKED)
    assert f"{passed} passed" in totals and f"{errors} errors" in totals, totals
    assert "failed" not in totals, totals


@pytest.mark.parametrize("name", PASSING)
def test_legitimate_traffic_and_opt_out_pass(result, name):
    assert _summary(result, name) == ["PASSED"], result.stdout


def test_allow_network_marker_is_registered(result):
    assert "PytestUnknownMarkWarning" not in result.stdout + result.stderr


def test_outer_process_env_is_scrubbed():
    assert not set(PROVIDER_ENV_VARS) & set(os.environ)
