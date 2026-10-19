"""Download the learning record: a .db snapshot or the full JSON export.

For container users, who cannot easily reach the db inside the Docker volume. Each request
builds its file in a private temp dir that is removed when the response ends — however it
ends (see _ScratchFileResponse). No new auth: the app binds 127.0.0.1 and every record is
already readable over GET.
"""

import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from starlette.types import Receive, Scope, Send

from adaptive_academy.engine.backup import BackupError, default_name, export_record, snapshot

router = APIRouter(prefix="/api/export", tags=["export"])

_PATHSEND = "http.response.pathsend"


class _ScratchFileResponse(FileResponse):
    """A FileResponse that always removes its scratch dir once the response is over.

    A BackgroundTask is not enough: FileResponse returns early (skipping it) for a malformed
    or unsatisfiable Range header, and a client disconnect aborts the send before it runs,
    either way leaving a full copy of the learning record in the temp dir.
    """

    def __init__(self, path: Path, scratch: Path, **kwargs) -> None:
        super().__init__(path, **kwargs)
        self._scratch = scratch

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # With pathsend the server reads the file only after this call returns, i.e. after
        # the scratch dir is gone, so hide the extension and stream the bytes ourselves.
        extensions = scope.get("extensions") or {}
        if _PATHSEND in extensions:
            scope = {**scope,
                     "extensions": {k: v for k, v in extensions.items() if k != _PATHSEND}}
        try:
            await super().__call__(scope, receive, send)
        finally:
            shutil.rmtree(self._scratch, ignore_errors=True)


def _download(write: Callable[[Path], Path], name: str, media_type: str) -> FileResponse:
    scratch = Path(tempfile.mkdtemp(prefix="aa-download-"))
    try:
        path = write(scratch / name)
    except BackupError as exc:
        shutil.rmtree(scratch, ignore_errors=True)
        raise HTTPException(500, str(exc)) from exc
    except BaseException:
        shutil.rmtree(scratch, ignore_errors=True)
        raise
    return _ScratchFileResponse(path, scratch, media_type=media_type, filename=name)


@router.get("/backup")
def download_backup() -> FileResponse:
    """A consistent SQLite snapshot of the whole db, restorable with `aa restore`."""
    return _download(snapshot, default_name("db"), "application/vnd.sqlite3")


@router.get("/record")
def download_record() -> FileResponse:
    """The versioned JSON export of every table (see engine/backup.py for the format)."""
    return _download(export_record, default_name("json"), "application/json")
