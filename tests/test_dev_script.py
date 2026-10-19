"""scripts/dev.sh (`just dev`) runs two servers and must never leave one behind.

The real servers are swapped for stub commands (AA_DEV_API_CMD / AA_DEV_WEB_CMD). Each stub is
a three-level tree like `uv -> uvicorn reloader -> worker` and `npm -> sh -> vite`: a root
shell (the server's pid) starts a middle shell that backgrounds a long `sleep` (the leaf).
The middle shell outlives its leaf, as a reloader would, so a missed middle pid shows up as a
survivor. Each level writes its pid to a file. The script runs under every POSIX shell found
here: dash (Debian's /bin/sh) and bash (macOS's /bin/sh) differ in how they reap jobs.
"""

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX shell script")

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "dev.sh"
SHELLS = [s for s in ("sh", "dash", "bash") if shutil.which(s)]
LEVELS = ("root", "mid", "leaf")


def _stub(name: str, tmp: Path) -> str:
    # \$ so the middle shell, not the root shell, expands $$ and $!.
    mid = (
        rf"echo \$$ > '{tmp}/{name}.mid'; sleep 300 & echo \$! > '{tmp}/{name}.leaf'; "
        "wait; exec sleep 301"
    )
    return f"echo $$ > '{tmp}/{name}.root'; echo {name}-up; sh -c \"{mid}\" & wait"


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):  # gone, or reused by another user
        return False
    return True


def _wait_until(pred, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(0.05)
    return pred()


def _start(shell: str, tmp_path: Path) -> tuple[subprocess.Popen, dict[str, int]]:
    env = {
        **os.environ,
        "AA_DEV_API_CMD": _stub("api", tmp_path),
        "AA_DEV_WEB_CMD": _stub("web", tmp_path),
        "TMPDIR": str(tmp_path),
    }
    proc = subprocess.Popen(
        [shell, str(SCRIPT)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    files = {f"{n}.{lvl}": tmp_path / f"{n}.{lvl}" for n in ("api", "web") for lvl in LEVELS}

    def written() -> bool:
        return all(p.exists() and p.read_text().strip() for p in files.values())

    assert _wait_until(written), "stub servers never started"
    return proc, {k: int(p.read_text()) for k, p in files.items()}


def _finish(proc: subprocess.Popen, pids: dict[str, int]) -> tuple[int, str]:
    try:
        out, _ = proc.communicate(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, _ = proc.communicate()
        _kill_all(pids)
        pytest.fail(f"dev.sh did not exit:\n{out}")
    return proc.returncode, out


def _kill_all(pids: dict[str, int]) -> None:
    for pid in pids.values():
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


def _assert_all_gone(pids: dict[str, int], out: str) -> None:
    gone = _wait_until(lambda: not any(_alive(p) for p in pids.values()))
    survivors = {k: p for k, p in pids.items() if _alive(p)}
    _kill_all(pids)  # never leak stubs into the rest of the test run
    assert gone, f"left behind: {survivors}\n{out}"


@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize("sig, code", [(signal.SIGINT, 130), (signal.SIGTERM, 143)])
def test_signal_stops_both_servers(shell, sig, code, tmp_path):
    proc, pids = _start(shell, tmp_path)
    assert all(_alive(p) for p in pids.values())

    proc.send_signal(sig)
    rc, out = _finish(proc, pids)

    _assert_all_gone(pids, out)
    assert rc == code, out
    assert "[api] api-up" in out and "[web] web-up" in out
    assert not list(tmp_path.glob("aa-dev.*")), "temp FIFO dir left behind"


@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize("dies", ["api", "web"])
def test_one_server_exiting_stops_the_other(shell, dies, tmp_path):
    """The dying server's own children are re-parented when it goes (a crashed `uv`, a
    SIGKILLed uvicorn reloader); the tree the poll loop remembered still covers them."""
    proc, pids = _start(shell, tmp_path)
    time.sleep(1.5)  # let the poll loop snapshot the trees at least once

    os.kill(pids[f"{dies}.root"], signal.SIGKILL)
    rc, out = _finish(proc, pids)

    _assert_all_gone(pids, out)
    assert rc != 0, out
    assert f"{dies} exited" in out
