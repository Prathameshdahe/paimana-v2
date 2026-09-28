#!/bin/sh
# Restore the database from a dump in ./backups (scripts/backup.* or the backup container wrote it). The api and
# backup containers are stopped for the restore, every object in the dump is dropped and recreated (pg_restore
# --clean --if-exists), then the containers start again. Asks for a "yes" first.
# Usage: sh scripts/restore.sh backups/paimana-YYYYMMDD-HHMMSS.dump
set -eu
cd "$(dirname "$0")/.."
file="${1:?usage: scripts/restore.sh backups/paimana-YYYYMMDD-HHMMSS.dump}"
name="$(basename "$file")"
[ -f "backups/${name}" ] || { echo "backups/${name} not found" >&2; exit 1; }
echo "This replaces the database with backups/${name}; the api and backup containers stop while it runs."
printf 'Type yes to continue: '
read -r ok
[ "$ok" = yes ] || { echo "cancelled"; exit 1; }
docker compose stop api backup
docker compose exec -T postgres sh -c \
    "pg_restore -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" --clean --if-exists --no-owner \"/backups/${name}\""
docker compose start api backup
echo "restored backups/${name}"
