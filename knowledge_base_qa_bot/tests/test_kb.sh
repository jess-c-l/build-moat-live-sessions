#!/bin/bash
# Usage: test_kb.sh <app_dir> <port> <kind: markdown|vector> <out_file>
set -u
APP_DIR="$1"; PORT="$2"; KIND="$3"; OUT="$4"
ROOT="/Users/jess/Documents/build-moat-live-sessions/knowledge_base_qa_bot"
PY="$APP_DIR/.venv/bin/python"
URL="http://localhost:$PORT"

: > "$OUT"
log(){ echo "$@" >> "$OUT"; }

# helper: POST /chat, capture body + total time
chat(){
  local q="$1"
  local resp
  resp=$(curl -s -w "\n__TIME__%{time_total}s __CODE__%{http_code}" \
    -X POST "$URL/chat" -H "Content-Type: application/json" \
    -d "{\"query\": \"$q\"}")
  echo "$resp"
}

start_server(){
  ( cd "$APP_DIR" && nohup "$PY" -m uvicorn app.main:app --port "$PORT" \
      > "/tmp/${KIND}_server.log" 2>&1 & echo $! > "/tmp/${KIND}.pid" )
  # wait for health (no foreground sleep; rely on curl retry)
  curl -s --retry 60 --retry-delay 1 --retry-connrefused --retry-all-errors \
    "$URL/health" > /dev/null 2>&1
}

stop_server(){
  if [ -f "/tmp/${KIND}.pid" ]; then kill "$(cat /tmp/${KIND}.pid)" 2>/dev/null; fi
  # wait for port release via retry on connect-refused (negated): poll until fail
  for _ in $(seq 1 30); do
    if ! curl -s --max-time 1 "$URL/health" >/dev/null 2>&1; then break; fi
  done
}

# --- reproduce "not indexed" state ---
if [ "$KIND" = "markdown" ]; then rm -f "$ROOT/.kb/index.json"; else rm -rf "$ROOT/.kb/faiss_index"; fi

log "### [1] cold start, /chat BEFORE /index (expect: not indexed yet)"
start_server
log "$(chat 'How long do refunds take?')"
log ""

log "### [2] POST /index"
log "$(curl -s -w "\n__TIME__%{time_total}s __CODE__%{http_code}" -X POST "$URL/index")"
log ""

log "### [3] inspect persisted index"
if [ "$KIND" = "markdown" ]; then
  log "\$ head -c 600 .kb/index.json"
  log "$(head -c 600 "$ROOT/.kb/index.json")"
else
  log "\$ cat .kb/faiss_index/metadata.json"
  log "$(cat "$ROOT/.kb/faiss_index/metadata.json")"
  log "\$ ls .kb/faiss_index/"
  log "$(ls "$ROOT/.kb/faiss_index/")"
fi
log ""

log "### [4] RESTART server, then /chat WITHOUT /index (persistence test)"
stop_server
start_server
log "$(chat 'How long do refunds take?')"
log ""

log "### [5] grounded Q: email change (expect cite account_help.md#change-email-address)"
log "$(chat 'Can I change my email address?')"
log ""

log "### [6] out-of-scope Q: restaurants (expect: cannot confirm)"
log "$(chat 'Which restaurants are nearby?')"
log ""

log "### [7] extra Q: Help me change my email address to jess@gmail.com"
log "$(chat 'Help me change my email address to jess@gmail.com')"
log ""

stop_server
log "### DONE ($KIND)"
