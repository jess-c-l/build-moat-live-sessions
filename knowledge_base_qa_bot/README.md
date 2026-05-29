# Knowledge Base Q&A Bot

針對 `docs/*.md` 知識庫的 grounded Q&A bot，提供兩種檢索策略可比較：

| 策略 | 資料夾 | 檢索方式 | 持久化索引 |
| --- | --- | --- | --- |
| **Markdown KB** | `scaffold/markdown_kb/` | heading section + BM25 關鍵字（純本地） | `.kb/index.json` |
| **Vector RAG** | `scaffold/vector_rag/` | chunk + embeddings + FAISS 語意檢索 | `.kb/faiss_index/` |

共用 API：`GET /health`、`POST /index`（讀 `docs/*.md` 建索引）、`POST /chat`（grounded 作答並附 sources）。重啟後 startup 會自動載回索引，不需重建；改了 `docs/*.md` 才需重跑 `/index`。

---

## 環境準備

兩個 scaffold 各自有獨立 venv 與 `.env`。在各自資料夾建立 `.env`：

```env
LLM_PROVIDER=google          # openai（預設）或 google
OPENAI_API_KEY=sk-...         # 預設 provider 用
GOOGLE_API_KEY=...            # LLM_PROVIDER=google 時用
GOOGLE_MODEL=gemini-2.5-flash
```

- Markdown KB：**只有生成答案**需要 API key。
- Vector RAG：**index、query、生成都需要** API key（embedding 也走 API）。

---

## 啟動 Markdown KB

```bash
cd scaffold/markdown_kb
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

## 啟動 Vector RAG

```bash
cd scaffold/vector_rag
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

> 兩者都監聽 8000，請**一次只跑一個**；若要並跑，把其中一個換成 `--port 8001`。

---

## 測試

server 起來後依序執行（兩種策略共用同一組指令）：

```bash
# 1. 健康檢查
curl http://localhost:8000/health
# -> {"status":"ok"}

# 2. 未 index 先問 -> 應提示尚未建索引
curl -X POST http://localhost:8000/chat -H "Content-Type: application/json" \
  -d '{"query": "How long do refunds take?"}'

# 3. 建索引
curl -X POST http://localhost:8000/index
# -> {"files_indexed": 3, "sections_indexed": 12}

# 4. 檢視持久化索引
cat .kb/index.json              # Markdown KB
cat .kb/faiss_index/metadata.json   # Vector RAG

# 5. 重啟 server、不再 /index，直接問（驗證 startup 載入）
# 6. grounded 問題（應正確引用來源）
curl -X POST http://localhost:8000/chat -H "Content-Type: application/json" \
  -d '{"query": "How long do refunds take?"}'        # -> refund_policy.md#refund-timeline
curl -X POST http://localhost:8000/chat -H "Content-Type: application/json" \
  -d '{"query": "Can I change my email address?"}'   # -> account_help.md#change-email-address

# 7. 範圍外問題 -> 應回 cannot confirm
curl -X POST http://localhost:8000/chat -H "Content-Type: application/json" \
  -d '{"query": "Which restaurants are nearby?"}'
```

---

## 測試結果總結

兩種策略都跑過完整流程（`docs/` 三檔 → `files=3, sections/chunks=12`）。完整數據見 [`TEST_RESULTS.md`](./TEST_RESULTS.md)。

- **正確性**：兩者在 grounded 題都把正確 section 排第一、引用正確；範圍外題都不硬湊答案。
- **延遲**：grounded 題端到端「差不多」（~2–3s），因為都被 LLM 生成主宰；但
  - `/index`：Markdown `0.004s` vs Vector `1.8s`（embedding API，約 480×）。
  - 範圍外題：Markdown `0.001s`（BM25=0 直接短路、**不呼叫 LLM**）vs Vector ~2.9s（仍要 embed query）。
- **API 依賴**：Vector 把「檢索」也變成外部 API 依賴（index + query + 生成三處），實測有幾題檢索成功、但生成撞到 Google 免費額度 `429`；Markdown 的 API 風險只集中在最後生成一處。

**結論**：在這個小型、結構化知識庫，Vector RAG 速度沒有比較快、召回也沒明顯優勢，卻多了 embedding 的成本與額度風險，因此選 **Markdown KB**。Vector RAG 的價值要到文件量大、同義詞多、自然語言查詢時才會顯現。
