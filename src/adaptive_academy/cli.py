import sys


def _graph_backfill() -> None:
    from sqlmodel import Session

    from adaptive_academy.db import engine
    from adaptive_academy.engine.graph import backfill

    with Session(engine) as session:
        result = backfill(session)
        session.commit()
    print(f"tracks={result.tracks} edges={result.edges} unresolved={result.unresolved}")


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    if cmd == "seed":
        from adaptive_academy.seed import seed

        seed()
    elif cmd == "graph-backfill":
        _graph_backfill()
    else:
        print("usage: aa {seed|graph-backfill}")


if __name__ == "__main__":
    main()
