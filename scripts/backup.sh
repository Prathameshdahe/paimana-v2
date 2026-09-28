#!/bin/sh
# A database dump now: pg_dump -Fc into ./backups/paimana-<UTC stamp>.dump through the backup container's script
# (deploy/backup.sh once), so it works from Windows and Linux alike and needs no client tools on the host.
# The daily dump and the retention are the backup container's job (docker-compose.yml). Restore: scripts/restore.*
set -eu
cd "$(dirname "$0")/.."
mkdir -p backups
docker compose run --rm backup once
