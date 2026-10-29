#!/usr/bin/env bash
# One-command end-to-end demo: seed -> GraphQL lifecycle -> outbox -> RabbitMQ -> DynamoDB -> Valkey -> Loki.
# Needs the lab stack: docker compose -p warehouse-fulfillment-lab up -d --wait postgres rabbitmq valkey dynamodb-local loki alloy
# Flags: --no-pause (no prediction pauses), --keep-data, --cleanup RUN_ID.
set -euo pipefail
cd "$(dirname "$0")/../.."
exec uv run python scripts/demo/run_demo.py "$@"
