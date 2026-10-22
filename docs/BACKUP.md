# Back up and restore

Your whole learning record (topics, concepts, assessments, conversations, and the agent log) is
one SQLite file:

- without Docker: `adaptive_academy.db` in the repo
- with Docker: `/data/adaptive_academy.db` in the `adaptive-academy-data` volume

## Back up

All of these are safe while the app is running.

From the app: open **Your data** in the sidebar and download either file.

From a terminal:

```bash
just backup                     # a .db snapshot in backups/
just export                     # the full record as JSON in backups/
uv run aa backup ~/somewhere/   # or choose the folder or file name yourself
```

From the container (or any machine that can reach it):

```bash
curl -OJ http://localhost:8000/api/export/backup   # .db snapshot
curl -OJ http://localhost:8000/api/export/record   # .json export
```

The `.db` snapshot is a complete copy you can restore. The `.json` export
(`"format": "adaptive-academy-export"`, `"version": 1`) has every table's rows, for reading or
moving to another tool. It leaves out the search indexes, which the app rebuilds. You can't
restore from it. `backups/` is gitignored.

## Restore

Restore from a `.db` snapshot. Stop the app first.

### Without Docker

```bash
uv run aa restore backups/adaptive_academy-YYYYMMDD-HHMMSS.db --force
uv run alembic upgrade head   # update an older snapshot to the current schema
```

`aa restore` won't replace your database unless you pass `--force`. It saves the current one to
`backups/adaptive_academy-pre-restore-*.db` first.

To do it by hand: stop the app, delete `adaptive_academy.db-wal` and `adaptive_academy.db-shm`
if they exist (an old WAL file would be applied on top of the restored data), copy the snapshot
to `adaptive_academy.db`, and run `uv run alembic upgrade head`.

### With Docker

Download a backup of your current data first. Then copy the snapshot into the volume. The
container updates the schema when it starts.

```bash
just down
docker run --rm -v adaptive-academy-data:/data -v "$PWD/backups":/host alpine sh -c '
  rm -f /data/adaptive_academy.db-wal /data/adaptive_academy.db-shm &&
  cp /host/adaptive_academy-YYYYMMDD-HHMMSS.db /data/adaptive_academy.db'
just up
```

Schema updates only go forward. An older version of the app can't open a database that a newer
version has updated. To go back to an older version, restore an older snapshot first.
