#!/bin/sh
# Entrypoint of the api image. Inside the compose stack the api, migrate, bootstrap and serve commands must reach the
# postgres container, while .env.db's DATABASE_URL points at the port published on the host (for pytest, alembic
# and psql run there). docker-compose.yml sets POSTGRES_HOST=postgres; when it is set, DATABASE_URL is rebuilt here
# from the POSTGRES_* lines of .env.db (keep the password URL-safe: scripts/first-run.* generates an alphanumeric
# one). Outside compose (no POSTGRES_HOST) DATABASE_URL is used as given. Only processes started through this
# entrypoint see the rebuilt value: `docker compose run --rm --no-deps api <command>` does, `docker compose exec`
# does not, so one-off commands (bootstrap, serve, alembic) use `run` (docs/DEPLOYMENT.md, One-off commands).
set -eu
if [ -n "${POSTGRES_HOST:-}" ]; then
    : "${POSTGRES_USER:?POSTGRES_USER is not set (.env.db)}"
    : "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is not set (.env.db)}"
    : "${POSTGRES_DB:?POSTGRES_DB is not set (.env.db)}"
    DATABASE_URL="postgresql+psycopg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_HOST_PORT:-5432}/${POSTGRES_DB}"
    export DATABASE_URL
fi
# The api's own start (not migrate, not a one-off command): make sure the hidden developer account exists and has the
# password .env.db gives it (PAIMANA_DEVELOPER_EMAIL / PAIMANA_DEVELOPER_PASSWORD; nothing happens without them). It
# never prompts and never prints a password; a failure is logged and the api starts anyway.
if [ "${1:-}" = "uvicorn" ]; then
    python -m backend.auth.bootstrap --developer-only \
        || echo "api-entrypoint: the developer bootstrap failed (see above); starting the api anyway" >&2
fi
exec "$@"
