#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:5000}"
API_KEY="${API_KEY:-}"
EXPECTED_REVISION="${EXPECTED_REVISION:-0009_reply_reliability}"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

echo "==> liveness"
curl -fsS --max-time 10 "$BASE_URL/health" | tee "$TMP_DIR/health.json"
echo

echo "==> readiness"
READY_CODE="$(curl -sS --max-time 15 -o "$TMP_DIR/ready.json" -w '%{http_code}' "$BASE_URL/ready")"
cat "$TMP_DIR/ready.json"
echo
if [ "$READY_CODE" != "200" ]; then
  echo "readiness failed: HTTP=$READY_CODE"
  exit 1
fi
python3 - "$TMP_DIR/ready.json" "$EXPECTED_REVISION" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
expected = sys.argv[2]
assert payload.get("status") == "ready", payload
assert payload.get("database") is True, payload
assert payload.get("migration") is True, payload
assert payload.get("schema_revision") == expected, payload
PY

if [ -n "$API_KEY" ]; then
  echo "==> bridge metrics"
  curl -fsS --max-time 15 \
    -H "X-API-Key: $API_KEY" \
    "$BASE_URL/api/v1/personal-wechat/metrics" \
    | tee "$TMP_DIR/metrics.json"
  echo
  python3 - "$TMP_DIR/metrics.json" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
manual = int(payload.get("manual_review") or 0)
retrying = int(payload.get("retrying") or 0)
if manual > 0:
    print(f"warning: manual_review tasks={manual}")
if retrying > 100:
    raise SystemExit("retry backlog exceeds 100")
PY
fi

echo "release readiness checks passed"
