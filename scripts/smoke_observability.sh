#!/usr/bin/env bash
# Real end-to-end proof: run the API on the host, force an unhandled error, find the line in Loki.
# Needs: `docker compose -p warehouse-fulfillment-lab up -d --wait postgres loki alloy`.
set -euo pipefail
cd "$(dirname "$0")/.."

PG_URL=${LAB_SMOKE_DATABASE_URL:-postgresql+psycopg://lab:lab@127.0.0.1:55432/warehouse_lab}
LOKI=${LAB_SMOKE_LOKI_URL:-http://127.0.0.1:53100}
PORT=${LAB_SMOKE_PORT:-5099}
REQUEST_ID="smoke-$(date +%s)"
SCHEMA="lab_smoke_$$"
mkdir -p logs

# An existing but empty schema: the app starts, then every order query fails with a
# missing-table error, which is the "unhandled error" we want to observe.
docker compose -p warehouse-fulfillment-lab exec -T postgres \
  psql -q -U lab -d warehouse_lab -c "CREATE SCHEMA \"$SCHEMA\""

API_PID=
cleanup() {
  [ -n "$API_PID" ] && kill "$API_PID" 2>/dev/null || true
  docker compose -p warehouse-fulfillment-lab exec -T postgres \
    psql -q -U lab -d warehouse_lab -c "DROP SCHEMA \"$SCHEMA\" CASCADE" || true
}
trap cleanup EXIT

LAB_DATABASE_URL="$PG_URL?options=-csearch_path%3D$SCHEMA" \
  uv run flask --app 'api.app_factory:create_app_from_environment' run --port "$PORT" \
  2>> logs/backend.log &
API_PID=$!

for _ in $(seq 1 40); do
  curl -sf "http://127.0.0.1:$PORT/health" >/dev/null && break
  sleep 0.5
done

echo "-> triggering an unhandled error with X-Request-Id: $REQUEST_ID"
curl -s "http://127.0.0.1:$PORT/graphql" -H 'Content-Type: application/json' \
  -H 'X-Client-Id: smoke' -H "X-Request-Id: $REQUEST_ID" -D - \
  -d '{"query":"{ order(orderId: \"o1\") { orderId } }"}'
echo

echo "-> polling Loki for the line"
for _ in $(seq 1 30); do
  RESULT=$(curl -sG "$LOKI/loki/api/v1/query_range" \
    --data-urlencode "query={service=\"backend\", level=\"ERROR\"} |= \"$REQUEST_ID\"" \
    --data-urlencode "start=$(( $(date +%s) - 300 ))000000000" --data-urlencode "limit=5")
  if [ "$(printf '%s' "$RESULT" | uv run python -c 'import json,sys; print(len(json.load(sys.stdin)["data"]["result"]))')" != 0 ]; then
    printf '%s' "$RESULT" | uv run python -c '
import json, sys
stream = json.load(sys.stdin)["data"]["result"][0]
print("labels:", stream["stream"])
line = json.loads(stream["values"][0][1])
line["exception"] = line["exception"].splitlines()[-1] + "  [traceback trimmed]"
print("line:  ", json.dumps(line))'
    echo "OK: the error reached Loki"
    exit 0
  fi
  sleep 1
done
echo "FAIL: the line did not reach Loki within 30 s" >&2
exit 1
