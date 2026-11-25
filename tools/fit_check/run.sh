#!/usr/bin/env bash
# Fit check calibration matrix (docs/11 "Calibration"): runs tools/fit_check/matrix.py in the backend container and
# copies the result to tools/fit_check/out/ (gitignored). Usage: tools/fit_check/run.sh [cases.json]
set -euo pipefail
cd "$(dirname "$0")/../.."
export PATH="$PATH:$HOME/.orbstack/bin"
args=(--out /tmp/fit_check)
if [ $# -ge 1 ]; then
  docker compose cp "$1" backend:/tmp/fit_cases.json
  args+=(--cases /tmp/fit_cases.json)
fi
docker compose exec -T backend python - "${args[@]}" < tools/fit_check/matrix.py
mkdir -p tools/fit_check/out
docker compose cp backend:/tmp/fit_check/. tools/fit_check/out/
echo "copied to tools/fit_check/out/"
