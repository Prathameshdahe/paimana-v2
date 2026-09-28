#!/bin/sh
# The demo stack's one-shot init (docker-compose.demo.yml, service init), run through deploy/api-entrypoint.sh so
# DATABASE_URL points at the stack's postgres: the extensions the migrations expect (the demo postgres has no init
# script mounted, and its user is the superuser), the schema (alembic upgrade head) and the serving tables
# (python -m pipeline.run serve). Every step is idempotent, so each `up` runs it again safely.
set -eu
python - <<'EOF'
import os
import psycopg
url = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://", 1)
with psycopg.connect(url, autocommit=True) as conn:
    conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    conn.execute("CREATE EXTENSION IF NOT EXISTS citext")
print("demo-init: vector and citext ready")
EOF
python -m alembic upgrade head
python -m pipeline.run serve
echo "demo-init: done"
