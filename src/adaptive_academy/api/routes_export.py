"""Download the learning record: a .db snapshot or the full JSON export.

For container users, who cannot easily reach the db inside the Docker volume. Each request
builds its file in a private temp dir that a BackgroundTask removes once the response is sent.
No new auth: the app binds 127.0.0.1 and every record is already readable over GET.
"""

import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from adaptive_academy.engine.backup import BackupError, default_name, export_record, snapshot

router = APIRouter(prefix="/api/export", tags=["export"])


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
    return FileResponse(
        path,
        media_type=media_type,
        filename=name,
        background=BackgroundTask(shutil.rmtree, scratch, ignore_errors=True),
    )


@router.get("/backup")
def download_backup() -> FileResponse:
    """A consistent SQLite snapshot of the whole db, restorable with `aa restore`."""
    return _download(snapshot, default_name("db"), "application/vnd.sqlite3")


@router.get("/record")
def download_record() -> FileResponse:
    """The versioned JSON export of every table (see engine/backup.py for the format)."""
    return _download(export_record, default_name("json"), "application/json")
