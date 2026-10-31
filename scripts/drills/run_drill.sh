#!/usr/bin/env bash
# Prediction-first failure drills against the lab stack: run_drill.sh <1-8|all> [--no-pause] [--keep-data]
# Needs: docker compose -p warehouse-fulfillment-lab up -d --wait postgres rabbitmq valkey dynamodb-local
# Other flag: --cleanup RUN_ID (delete a kept run's rows and exit). Drill 7 stops and restarts Valkey.
set -euo pipefail
cd "$(dirname "$0")/../.."
exec uv run python scripts/drills/run_drill.py "$@"
