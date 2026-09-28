#!/bin/sh
# Self-signed TLS certificate for a laptop or LAN demo: deploy/certs/fullchain.pem + privkey.pem, CN and subject
# alternative names from the first argument (default localhost; localhost and 127.0.0.1 are always included).
# openssl from PATH, else the one inside the pgvector/pgvector:pg16 image through Docker. Browsers warn once about
# it; a real server needs a CA certificate (docs/DEPLOYMENT.md, Real server). FORCE=1 replaces an existing pair.
set -eu
cd "$(dirname "$0")/.."
name="${1:-localhost}"
mkdir -p deploy/certs
if [ -s deploy/certs/fullchain.pem ] && [ -s deploy/certs/privkey.pem ] && [ "${FORCE:-0}" != 1 ]; then
    echo "deploy/certs already has a certificate (FORCE=1 to replace it)"
    exit 0
fi
export MSYS_NO_PATHCONV=1   # Git Bash on Windows would otherwise rewrite /CN=... as a path
san="subjectAltName=DNS:localhost,IP:127.0.0.1"
[ "$name" = localhost ] || san="subjectAltName=DNS:${name},DNS:localhost,IP:127.0.0.1"
if command -v openssl >/dev/null 2>&1; then
    openssl req -x509 -newkey rsa:2048 -nodes -days 825 -subj "/CN=${name}" -addext "$san" \
        -keyout deploy/certs/privkey.pem -out deploy/certs/fullchain.pem
else
    echo "openssl not found; using the one in the pgvector/pgvector:pg16 image"
    docker run --rm -v "$(pwd)/deploy/certs:/certs" pgvector/pgvector:pg16 \
        openssl req -x509 -newkey rsa:2048 -nodes -days 825 -subj "/CN=${name}" -addext "$san" \
        -keyout /certs/privkey.pem -out /certs/fullchain.pem
fi
chmod 600 deploy/certs/privkey.pem 2>/dev/null || true
echo "wrote deploy/certs/fullchain.pem and privkey.pem for ${name} (self-signed, 825 days)"
