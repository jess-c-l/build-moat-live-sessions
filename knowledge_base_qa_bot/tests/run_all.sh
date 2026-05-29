#!/bin/bash
# 一鍵重跑 Markdown KB 與 Vector RAG 的完整測試。
# 用法：bash tests/run_all.sh
# 前提：API 額度可用（Google 免費額度每日 20 次、每分鐘 5 次；額度滿時 /chat 生成會回 429）。
set -u
ROOT="/Users/jess/Documents/build-moat-live-sessions/knowledge_base_qa_bot"
SCAFFOLD="$ROOT/scaffold"
HERE="$ROOT/tests"

echo "===== Markdown KB (:8001) ====="
bash "$HERE/test_kb.sh" "$SCAFFOLD/markdown_kb" 8001 markdown "$HERE/md_results.txt"
cat "$HERE/md_results.txt"

echo
echo "===== Vector RAG (:8002) ====="
bash "$HERE/test_kb.sh" "$SCAFFOLD/vector_rag" 8002 vector "$HERE/vec_results.txt"
cat "$HERE/vec_results.txt"

echo
echo "輸出已存：tests/md_results.txt、tests/vec_results.txt"
