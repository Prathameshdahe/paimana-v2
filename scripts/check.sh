#!/bin/sh
# Every check the build must pass, in the order .github/workflows/check.yml runs them: pytest, then the frontend
# lint, typecheck and build. Stops at the first failure. Run from anywhere with the venv active.
set -eu
cd "$(dirname "$0")/.."
python -m pytest -q
cd frontend
npm run lint
npm run typecheck
npm run build
echo "all checks passed"
