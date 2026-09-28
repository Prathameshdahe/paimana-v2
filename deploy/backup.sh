#!/bin/bash
# pg_dump of the application database into /backups (./backups on the host), custom format, one file per run:
#   backup.sh once   one dump now (scripts/backup.* run this through `docker compose run --rm backup once`)
#   backup.sh loop   the backup container: a dump every day at BACKUP_HOUR (UTC), keeping BACKUP_KEEP_DAYS days
# Runs in the pgvector/pgvector:pg16 image with .env.db (POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB) and PGHOST.
# Files are written by root with mode 600 and renamed into place only when pg_dump succeeded.
set -eu
umask 077
export PGPASSWORD="${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is not set (.env.db)}"
host="${PGHOST:-postgres}"
dir="${BACKUP_DIR:-/backups}"
keep="${BACKUP_KEEP_DAYS:-14}"

dump() {
    local stamp out
    stamp="$(date -u +%Y%m%d-%H%M%S)"
    out="${dir}/paimana-${stamp}.dump"
    pg_dump -h "$host" -U "$POSTGRES_USER" -Fc --no-owner -f "${out}.part" "$POSTGRES_DB"
    mv "${out}.part" "$out"
    find "$dir" -maxdepth 1 -name 'paimana-*.dump' -type f -mtime +"$((keep - 1))" -delete
    echo "backup: wrote ${out} ($(du -h "$out" | cut -f1)); keeping ${keep} days"
}

case "${1:-once}" in
    once) dump ;;
    loop)
        hour="${BACKUP_HOUR:-02}"
        while true; do
            now="$(date -u +%s)"
            next="$(date -u -d "today ${hour}:00" +%s)"
            if [ "$next" -le "$now" ]; then next="$(date -u -d "tomorrow ${hour}:00" +%s)"; fi
            echo "backup: next dump at $(date -u -d "@${next}" +%FT%TZ)"
            sleep $((next - now))
            dump || echo "backup: FAILED at $(date -u +%FT%TZ)" >&2
        done ;;
    *) echo "usage: backup.sh [once|loop]" >&2; exit 2 ;;
esac
