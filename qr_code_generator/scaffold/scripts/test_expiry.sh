#!/usr/bin/env bash
# 測試過期自動回 410:建立 20 秒後過期的 QR,過期前 302、過期後 410
set -e

BASE="http://localhost:8000"
TTL_SECONDS=20

pass() { echo "✓ $1"; }
fail() { echo "✗ $1" >&2; exit 1; }

EXPIRES=$(python3 -c "
from datetime import datetime, timedelta
print((datetime.utcnow() + timedelta(seconds=$TTL_SECONDS)).isoformat())
")

echo "=== 1. POST /api/qr/create (expires_at = now + ${TTL_SECONDS}s = $EXPIRES) ==="
RESP=$(curl -s -X POST "$BASE/api/qr/create" \
  -H "Content-Type: application/json" \
  -d "{\"url\": \"https://example.com/expiry-test\", \"expires_at\": \"$EXPIRES\"}")
echo "$RESP"
TOKEN=$(echo "$RESP" | python3 -c "import sys, json; print(json.load(sys.stdin)['token'])")
[ -n "$TOKEN" ] && pass "建立成功 token=$TOKEN" || fail "建立失敗"

echo
echo "=== 2. GET /r/$TOKEN 過期前 (期望 302) ==="
CODE=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/r/$TOKEN")
echo "HTTP: $CODE"
[ "$CODE" = "302" ] && pass "過期前回 302" || fail "expected 302 got $CODE"

WAIT=$((TTL_SECONDS + 2))
echo
echo "=== 等 ${WAIT} 秒讓它過期 ==="
for i in $(seq "$WAIT" -1 1); do
  printf "\r  剩 %2d 秒..." "$i"
  sleep 1
done
echo

echo
echo "=== 3. GET /r/$TOKEN 過期後 (期望 410) ==="
CODE=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/r/$TOKEN")
echo "HTTP: $CODE"
[ "$CODE" = "410" ] && pass "過期後回 410" || fail "expected 410 got $CODE"

echo
echo "=== 4. 再打一次 (cache 已被 inline pop,DB 也判斷過期 → 仍是 410) ==="
CODE=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/r/$TOKEN")
echo "HTTP: $CODE"
[ "$CODE" = "410" ] && pass "重複請求依然 410" || fail "expected 410 got $CODE"

echo
echo "🎉 過期測試通過"
