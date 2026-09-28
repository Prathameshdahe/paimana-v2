#!/bin/sh
# First run of the production stack on a fresh checkout (docs/DEPLOYMENT.md, First run). Idempotent: every step
# skips what already exists, so it is safe to run again after a failure.
#   .env from .env.production.example, .env.db with a generated password, a self-signed certificate if none,
#   docker compose build, postgres up, migrate, the whole stack up, the first administrator, the serving tables,
#   and the URL to open.
# Usage: sh scripts/first-run.sh [--dev] [--skip-admin] [--skip-serve]
#   --dev         also use docker-compose.dev.yml (laptop ports 8443/8080/5434, a paimana_test database)
#   --skip-admin  do not run the administrator bootstrap (it refuses anyway once an administrator exists)
#   --skip-serve  do not load the serving tables (python -m pipeline.run serve)
set -eu
cd "$(dirname "$0")/.."
dev=0
admin=1
serve=1
for a in "$@"; do
    case "$a" in
        --dev) dev=1 ;;
        --skip-admin) admin=0 ;;
        --skip-serve) serve=0 ;;
        *) echo "unknown option: $a" >&2; exit 2 ;;
    esac
done
compose() {
    if [ "$dev" = 1 ]; then docker compose -f docker-compose.yml -f docker-compose.dev.yml "$@"
    else docker compose "$@"; fi
}
docker info >/dev/null 2>&1 || { echo "Docker is not running" >&2; exit 1; }

if [ ! -f .env ]; then
    cp .env.production.example .env
    echo ".env written from .env.production.example: set SERVER_NAME, ALLOWED_ORIGINS, ALLOWED_HOSTS for a real server"
fi
if [ ! -f .env.db ]; then
    pw="$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 32)"
    umask 077
    cat >.env.db <<EOF
# PAIMANA database credentials, written by scripts/first-run (never commit this file; docs/DEPLOYMENT.md).
# Inside the stack the api reaches postgres:5432 (deploy/api-entrypoint.sh builds DATABASE_URL from these lines).
# POSTGRES_PORT and DATABASE_URL are for tools run on the host against the port docker-compose.dev.yml publishes.
POSTGRES_USER=paimana
POSTGRES_PASSWORD=${pw}
POSTGRES_DB=paimana
POSTGRES_PORT=5434
DATABASE_URL=postgresql+psycopg://paimana:${pw}@localhost:5434/paimana
EOF
    umask 022
    echo ".env.db written with a generated password"
fi
mkdir -p backups dataset/raw/inbox dataset/rag temp
server="$(sed -n 's/^SERVER_NAME=//p' .env | head -n 1)"
case "$server" in ""|_) server=localhost ;; esac
if [ ! -s deploy/certs/fullchain.pem ]; then
    sh scripts/gen-dev-cert.sh "$server"
fi

echo "== building the images"
compose build
echo "== starting postgres"
compose up -d postgres
echo "== migrating the database"
compose run --rm migrate
echo "== starting the stack"
compose up -d
if [ "$admin" = 1 ]; then
    echo "== first administrator (the bootstrap asks for the password; it is never written to a file)"
    printf 'Administrator email: '
    read -r email
    printf 'Administrator name: '
    read -r name
    # one-off commands go through `run`, not `exec`: run starts the image's entrypoint, which points DATABASE_URL
    # at the stack's postgres (deploy/api-entrypoint.sh); exec would see .env.db's host-side URL
    compose run --rm --no-deps api python -m backend.auth.bootstrap --email "$email" --name "$name" \
        || echo "no administrator was created (one may exist already; --force-reset in the bootstrap resets it)"
fi
if [ "$serve" = 1 ]; then
    echo "== loading the serving tables"
    compose run --rm --no-deps api python -m pipeline.run serve
fi
if [ "$dev" = 1 ]; then
    url="https://localhost:8443"
else
    port="$(sed -n 's/^WEB_HTTPS_PORT=//p' .env | head -n 1)"
    case "$port" in ""|443) url="https://${server}" ;; *) url="https://${server}:${port}" ;; esac
fi
echo "== up: open ${url}  (docker compose ps / logs -f show the state; docs/DEPLOYMENT.md has the rest)"
