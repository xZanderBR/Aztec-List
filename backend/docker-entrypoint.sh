#!/bin/sh
# Container entrypoint: prepare the data volume, apply migrations, then start the API.
#
# Runs as root only long enough to fix volume ownership (Fly volumes mount root-owned,
# which would block the unprivileged `app` user from writing uploads or the SQLite DB),
# then re-executes itself as `app`. Migrations run here rather than in a Fly
# release_command because release machines do not mount volumes, so they could not
# reach a SQLite database stored on one.
set -eu

DATA_DIR="${DATA_DIR:-/data}"

if [ "$(id -u)" = "0" ]; then
  mkdir -p "$DATA_DIR/uploads" "$DATA_DIR/qdrant"
  chown -R app:app "$DATA_DIR"
  exec setpriv --reuid=app --regid=app --init-groups "$0" "$@"
fi

# Production manages the schema with Alembic (main.py skips create_all there). Dev and
# docker-compose use create_all, so running migrations against those databases would
# collide with the tables it already created.
if [ "${APP__ENVIRONMENT:-development}" = "production" ]; then
  alembic upgrade head
fi
exec "$@"
