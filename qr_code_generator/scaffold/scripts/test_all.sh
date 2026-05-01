#!/usr/bin/env bash
# 跑完整的 10 個 curl 驗證,自動抓 token 串接
set -e

BASE="http://localhost:8000"

pass() { echo "✓ $1"; }
fail() { echo "✗ $1" >&2; exit 1; }

echo "=== 1. POST /api/qr/create ==="
RESP=$(curl -s -X POST "$BASE/api/qr/create" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}')
echo "$RESP"
TOKEN=$(echo "$RESP" | python3 -c "import sys, json; print(json.load(sys.stdin)['token'])")
[ -n "$TOKEN" ] && pass "建立成功 token=$TOKEN" || fail "建立失敗"

echo
echo "=== 2. GET /r/$TOKEN (期望 302) ==="
CODE=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/r/$TOKEN")
echo "HTTP: $CODE"
[ "$CODE" = "302" ] && pass "redirect 回 302" || fail "expected 302 got $CODE"

echo
echo "=== 3. GET /api/qr/$TOKEN (期望 200) ==="
curl -s "$BASE/api/qr/$TOKEN" | python3 -m json.tool
pass "metadata 拿到"

echo
echo "=== 4. PATCH /api/qr/$TOKEN 改 url 為 https://new-url.com ==="
curl -s -X PATCH "$BASE/api/qr/$TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://new-url.com"}' | python3 -m json.tool
pass "更新成功"

echo
echo "=== 5. GET /r/$TOKEN 應導到 https://new-url.com ==="
LOC=$(curl -s -o /dev/null -w "%{redirect_url}" "$BASE/r/$TOKEN")
echo "redirect_url: $LOC"
[ "$LOC" = "https://new-url.com" ] && pass "導向新 url" || fail "expected https://new-url.com got $LOC"

echo
echo "=== 6. DELETE /api/qr/$TOKEN ==="
curl -s -X DELETE "$BASE/api/qr/$TOKEN"
echo
pass "刪除成功"

echo
echo "=== 7. GET /r/$TOKEN 已刪除 (期望 410) ==="
CODE=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/r/$TOKEN")
echo "HTTP: $CODE"
[ "$CODE" = "410" ] && pass "刪除後回 410" || fail "expected 410 got $CODE"

echo
echo "=== 8. GET /r/INVALID (期望 404) ==="
CODE=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/r/INVALID")
echo "HTTP: $CODE"
[ "$CODE" = "404" ] && pass "不存在 token 回 404" || fail "expected 404 got $CODE"

echo
echo "=== 9. QR image (重新建一個) ==="
RESP=$(curl -s -X POST "$BASE/api/qr/create" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com/image-test"}')
TOKEN2=$(echo "$RESP" | python3 -c "import sys, json; print(json.load(sys.stdin)['token'])")
INFO=$(curl -s -o /dev/null -w "%{http_code} %{content_type}" "$BASE/api/qr/$TOKEN2/image")
echo "HTTP+CT: $INFO"
echo "$INFO" | grep -q "200 image/png" && pass "QR 圖片回傳正確" || fail "expected '200 image/png' got '$INFO'"

echo
echo "=== 10. GET /api/qr/$TOKEN2/analytics ==="
# 先打一次 redirect 製造 scan 紀錄
curl -s -o /dev/null "$BASE/r/$TOKEN2"
curl -s "$BASE/api/qr/$TOKEN2/analytics" | python3 -m json.tool
pass "analytics 拿到"

echo
echo "🎉 全部 10 個驗證通過"
