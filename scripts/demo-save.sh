#!/bin/sh
# The demo stack's three images in one file, for a machine without internet (README, Quick start): builds the demo
# images (docker-compose.demo.yml), pulls postgres, and writes ./paimana-demo-images.tar.gz (gitignored).
# On the other machine, next to a copy of the repository:
#   docker load -i paimana-demo-images.tar.gz
#   docker compose -f docker-compose.demo.yml up -d
set -eu
cd "$(dirname "$0")/.."
docker info >/dev/null 2>&1 || { echo "Docker is not running" >&2; exit 1; }
docker compose -f docker-compose.demo.yml build
docker compose -f docker-compose.demo.yml pull postgres
docker save paimana-demo-api paimana-demo-web pgvector/pgvector:pg16 | gzip > paimana-demo-images.tar.gz
echo "wrote paimana-demo-images.tar.gz ($(du -h paimana-demo-images.tar.gz | cut -f1))"
