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
import socket
import sys

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

    client = anthropic.Anthropic(api_key="sk-ant-test-not-a-real-key", max_retries=0)
    with pytest.raises(anthropic.APIConnectionError):
        client.messages.create(model="claude-haiku-5-5", max_tokens=1,
                               messages=[{"role": "user", "content": "hi"}])


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


@pytest.mark.parametrize("name,host", [
    ("test_swallowed_lookup", "guard-probe.example.invalid:443"),
    ("test_swallowed_connect_to_address", "192.0.2.1:443"),
    ("test_anthropic_sdk_transport_is_blocked", "api.anthropic.com:443"),
    ("test_agent_sdk_query_is_blocked", "claude CLI subprocess"),
    ("test_attempt_in_fixture_teardown", "teardown-probe.example.invalid:443"),
])
def test_swallowed_real_connection_fails_the_test_that_made_it(result, name, host):
    assert f"test_inner.py::{name} tried to reach the network: {host}" in result.stdout
    # The body passed (the error was swallowed or expected); the guard fails it at teardown.
    assert _summary(result, name) == ["PASSED", "ERROR"], result.stdout
    assert "scripted client" in result.stdout


def test_failure_is_attributed_only_to_the_offending_tests(result):
    assert result.returncode == 1, result.stdout + result.stderr
    totals = result.stdout.splitlines()[-1]
    assert "10 passed" in totals and "5 errors" in totals and "failed" not in totals, totals
    assert _summary(result, "test_clean_after_a_blocked_test") == ["PASSED"]


@pytest.mark.parametrize("name", [
    "test_testclient_still_works",
    "test_loopback_still_works",
    "test_provider_credentials_are_scrubbed",
    "test_marker_opts_out",
])
def test_legitimate_traffic_and_opt_out_pass(result, name):
    assert _summary(result, name) == ["PASSED"], result.stdout


def test_allow_network_marker_is_registered(result):
    assert "PytestUnknownMarkWarning" not in result.stdout + result.stderr


def test_outer_process_env_is_scrubbed():
    assert not set(PROVIDER_ENV_VARS) & set(os.environ)
