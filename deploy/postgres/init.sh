#!/bin/bash
# Runs once, when the pgdata volume is first created (the postgres image sources /docker-entrypoint-initdb.d/*.sh).
# Creates the extensions the migrations expect (vector for app.rag_chunks, citext for app.users.email) in the
# application database and, when PAIMANA_TEST_DB is set (docker-compose.dev.yml), the test database with the same
# extensions. Later starts skip this file; the migrations (python -m alembic upgrade head) build the schema.
set -e
psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<-'SQL'
    CREATE EXTENSION IF NOT EXISTS vector;
    CREATE EXTENSION IF NOT EXISTS citext;
SQL
if [ -n "${PAIMANA_TEST_DB:-}" ]; then
    psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d postgres \
        -c "CREATE DATABASE \"${PAIMANA_TEST_DB}\" OWNER \"${POSTGRES_USER}\""
    psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$PAIMANA_TEST_DB" \
        -c "CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS citext;"
    echo "paimana init: created ${PAIMANA_TEST_DB} with vector and citext"
fi
echo "paimana init: ${POSTGRES_DB} has vector and citext"
