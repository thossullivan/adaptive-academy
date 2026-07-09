#!/bin/sh
# Migrate, then serve. `set -e` makes a failed migration stop the container
# visibly in OrbStack instead of serving against a half-migrated schema.
set -e

alembic upgrade head
exec uvicorn adaptive_academy.api.app:app --host 0.0.0.0 --port 8000
