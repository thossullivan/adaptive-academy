import sys
from pathlib import Path

USAGE = "usage: aa {seed|graph-backfill|backup [PATH]|export [PATH]|restore PATH [--force]}"


def _graph_backfill() -> None:
    from sqlmodel import Session

    from adaptive_academy.db import engine
    from adaptive_academy.engine.graph import backfill

    with Session(engine) as session:
        result = backfill(session)
        session.commit()
    print(f"tracks={result.tracks} edges={result.edges} unresolved={result.unresolved}")


def _target(arg: str | None, kind: str) -> Path:
    """Where `aa backup`/`aa export` writes: a timestamped file in ./backups by default, in the
    given directory if PATH is one (or ends with a separator), else PATH itself."""
    from adaptive_academy.engine.backup import default_name

    if arg is None:
        folder = Path("backups")
    elif arg.endswith(("/", "\\")) or Path(arg).is_dir():
        folder = Path(arg)
    else:
        return Path(arg).absolute()
    folder.mkdir(parents=True, exist_ok=True)
    return (folder / default_name(kind)).absolute()


def _backup_cmd(args: list[str], kind: str) -> None:
    from adaptive_academy.engine.backup import export_record, snapshot

    if len(args) > 1:
        sys.exit(USAGE)
    write = snapshot if kind == "db" else export_record
    print(write(_target(args[0] if args else None, kind)))


def _restore_cmd(args: list[str]) -> None:
    from adaptive_academy.engine.backup import restore, sqlite_path

    force = "--force" in args
    paths = [a for a in args if a != "--force"]
    if len(paths) != 1:
        sys.exit(USAGE)
    pre = restore(Path(paths[0]), force=force)
    if pre is not None:
        print(f"previous database saved to {pre}")
    print(f"restored {paths[0]} into {sqlite_path()}")
    print("next: run `uv run alembic upgrade head` before starting the app")


def main() -> None:
    from adaptive_academy.engine.backup import BackupError

    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    args = sys.argv[2:]
    try:
        if cmd == "seed":
            from adaptive_academy.seed import seed

            seed()
        elif cmd == "graph-backfill":
            _graph_backfill()
        elif cmd == "backup":
            _backup_cmd(args, "db")
        elif cmd == "export":
            _backup_cmd(args, "json")
        elif cmd == "restore":
            _restore_cmd(args)
        else:
            print(USAGE)
    except BackupError as exc:
        sys.exit(f"aa {cmd}: {exc}")


if __name__ == "__main__":
    main()
