# Knowledge Base Q&A Bot 實作計畫

> 目標：基於 `scaffold/markdown_kb`（Strategy A: Markdown KB）完成可通過 `PROMPT.md` 中所有 `curl` 驗證的 Q&A bot。
> Design Questions 已於 `DESIGN_ANS.md` 完成，本計畫聚焦在「實作」與「驗證」。

---

## 一、現況盤點

- `docs/` 已含三份 Markdown：`refund_policy.md`、`account_help.md`、`shipping_faq.md`
- `scaffold/markdown_kb/app/` 已有骨架，大部分 function 內為 `TODO`：
  - `indexer.py`：`parse_markdown`、`write_index_json`、`rebuild_stats`、`load_index_json`、`build_index`、`bm25_score`
  - `retrieval.py`：`SYSTEM_PROMPT`、`build_prompt`
- 已有 `main.py`（startup 時呼叫 `load_index_json`）與 `routes.py`（`/health`、`/index`、`/chat`）

---

## 二、實作步驟（依執行順序）

### Step 1. 環境準備
- [x] 進入 `scaffold/markdown_kb/`
- [x] 建立虛擬環境並安裝 `requirements.txt`
- [x] `export OPENAI_API_KEY="sk-..."`
- [x] 試跑 `uvicorn app.main:app --reload --port 8000`，確認 `/health` 回 `{"status":"ok"}`
  - 第一次設定：
  ```
    # 1. 進到 scaffold/markdown_kb（uvicorn 要在這層跑，因為 .env 和 app/ 都在這）
    cd /Users/jess/Documents/build-moat-live-sessions/knowledge_base_qa_bot/scaffold/markdown_kb
  
    # 2. 建虛擬環境（只做一次）
    python3 -m venv .venv
  
    # 3. 啟動 venv（每次新開 terminal 都要做）
    source .venv/bin/activate
    # 啟動後 prompt 前會出現 (.venv) 字樣
  
    # 4. 安裝套件（只做一次，或 requirements.txt 改了再做）
    pip install -r requirements.txt
    
    # 5. 跑 server
    uvicorn app.main:app --reload --port 8000
  ```
  - 重新啟動 server 時：
  ```
    cd /Users/jess/Documents/build-moat-live-sessions/knowledge_base_qa_bot/scaffold/markdown_kb
    source .venv/bin/activate
    uvicorn app.main:app --reload --port 8000
  ```


### Step 2. 實作 `indexer.parse_markdown`
- [x] 用 `HEADING_RE` 偵測 `#` 標題，切出每個 heading section
- [x] 維護 `heading_path`（堆疊各層 heading，從 `#` 到 `######`）
- [x] 每個 section 產出 `id = "<filename>#<slug(heading)>"`，例如 `refund_policy.md#refund-timeline`
- [x] `tokens` 同時涵蓋 heading 與 content（使用 `tokenize`）
- [x] 文件開頭若有非 heading 內容，略過或併入第一個 section（依設計擇一即可）

### Step 3. 實作 `indexer.rebuild_stats`
- [x] `files_indexed`：`{s.file for s in sections}` 的數量
- [x] `doc_freq`：每個 token 在多少 section 出現過（用 `set(tokens)` 避免重複計算）
- [x] `avg_doc_len`：所有 section `len(tokens)` 的平均

  -  files_indexed │ 給 /index API 回傳「掃了幾檔」         │ Step 5 build_index 的 return 值     
```
  refund_policy.md, account_help.md, shipping_faq.md
```
   
  - 12 個 sections

  - avg_doc_len   │ BM25 長度正規化（避免長 section 佔便宜） │ Step 6 bm25_score 分母        
```
    avg_doc_len = total_len / len(sections)
    把 12 個 section 的 token 數量加起來：
      
    refund_policy.md :  2 + 25 + 21 + 18 = 66
    account_help.md  :  2 + 21 + 15 + 14 = 52
    shipping_faq.md  :  2 + 14 + 19 + 13 = 48
                                        ----
    total                              = 166
    avg_doc_len = 166 / 12 ≈ 13.83
```
    
  - doc_freq      │ BM25 的 IDF：愈罕見的字權重愈高          │ Step 6 idf = log((N - df + 0.5)/(df + 0.5) + 1)
```
    ┌────────────────────┬─────────────────────────────────────────────────────────────────────────────────┐
    │      section       │                                shipping 出現位置                                 │
    ├────────────────────┼─────────────────────────────────────────────────────────────────────────────────┤
    │ shipping-faq (H1)  │ heading "Shipping FAQ"                                                          │
    ├────────────────────┼─────────────────────────────────────────────────────────────────────────────────┤
    │ standard-shipping  │ heading + content "Standard shipping usually..."                                │
    ├────────────────────┼─────────────────────────────────────────────────────────────────────────────────┤
    │ expedited-shipping │ heading + content "Expedited shipping usually...", "Expedited shipping fees..." │
    ├────────────────────┼─────────────────────────────────────────────────────────────────────────────────┤
    │ tracking-number    │ content "...the warehouse creates the shipping label."                          │
    └────────────────────┴─────────────────────────────────────────────────────────────────────────────────┘
  
    → 4 個 sections 都含 shipping，所以 doc_freq['shipping'] = 4。
```

### Step 4. 實作 `indexer.write_index_json` / `load_index_json`
- [x] `write_index_json`：
  - [x] `index_path.parent.mkdir(parents=True, exist_ok=True)`
  - [x] 輸出 `{"sections": [section.to_dict() ...], "stats": {"files_indexed": ..., "avg_doc_len": ...}}`，用 `indent=2` 方便檢視
- [x] `load_index_json`：
  - [x] 不存在直接回 `(0, 0)`
  - [x] 將 JSON 中的 section 還原為 `Section` dataclass，賦值給模組級 `sections`
  - [x] 呼叫 `rebuild_stats()`，回傳 `(files_indexed, len(sections))`

### Step 5. 實作 `indexer.build_index` ✅
- [x] 掃 `docs_dir.glob("*.md")`，對每檔呼叫 `parse_markdown`
- [x] 合併成全域 `sections`
- [x] 呼叫 `rebuild_stats()` 與 `write_index_json()`
- [x] 回傳 `(files_indexed, len(sections))`
- 驗證：刪 `.kb/index.json` → `build_index()` → 回 `(3, 12)`，產出 7220 bytes index.json → 清空 in-memory → `load_index_json()` 還原 `(3, 12)`，`doc_freq['refund']=2` 重建成功

### Step 6. 實作 `indexer.bm25_score`
- [x] 對每個 query token 算 `tf`（在該 section tokens 中出現次數）
- [x] `idf = log((N - df + 0.5) / (df + 0.5) + 1)`，其中 `N = len(sections)`、`df = doc_freq[token]`
- [x] 分母含 `k1 * (1 - b + b * len(section.tokens) / avg_doc_len)` 做長度正規化
- [x] 加分項：若 token 出現於 `heading_path`，加一個小 boost（例如 `+0.5 * idf`）

### Step 7. 實作 `retrieval.SYSTEM_PROMPT`
- [x] 限定「只根據 CONTEXT 回答」
- [x] 引用格式必須是 `[Source: filename#heading]`，且只能引用 CONTEXT 內出現過的 ID
- [x] 缺資訊時回 `I cannot confirm from the knowledge base.`
- [x] 嚴禁猜測或使用外部知識

### Step 8. 實作 `retrieval.build_prompt`
- [x] 對每個 ranked section，輸出格式：
  ```
  [Source: <section.id>]
  Heading path: <" > ".join(heading_path)>
  <section.content>
  ```
- [x] 全部組成 `CONTEXT:\n...\n\nQUESTION:\n<query>`

### Step 9. 重啟驗證持久化
- [x] `POST /index` 後檢查 `.kb/index.json` 是否正確生成
- [x] 停掉 server，再啟動後不呼叫 `/index`，直接 `/chat`，應該載入舊 index 正常作答

---

## 三、Verification Checklist（對應 `PROMPT.md`）

依序執行並截圖／保留輸出：

- [x] `curl http://localhost:8000/health` → `{"status":"ok"}`
- [x] 未 index 前 `POST /chat` → 提示「knowledge base 尚未 index」
```
  要驗證 checklist 那條「未 index 前提示」，得先清掉持久化的 index 再重啟：
  rm /Users/jess/Documents/build-moat-live-sessions/knowledge_base_qa_bot/.kb/index.json
```
- [ ] `POST /index` → `{"files_indexed": 3, "sections_indexed": N}`
- [ ] `cat .kb/index.json` 能看到結構化 sections
- [ ] 重啟 server，未再呼叫 `/index`，可直接 `/chat`
- [ ] 問「How long do refunds take?」→ 引用 `refund_policy.md#refund-timeline`
- [ ] 問「Can I change my email address?」→ 引用 `account_help.md#change-email-address`
- [ ] 問「Which restaurants are nearby?」→ 回 `cannot confirm from the knowledge base`

---

## 四、（選做）Stretch Goals 優先順序

若核心流程完成有餘力，建議順序：

1. **Score Threshold and Fallback**：在 `retrieval.query` 加入最低分閾值，未達門檻直接 fallback，最容易做且大幅提升答案品質
2. **Wiki Index Generation**：從 `.kb/index.json` 產出 `wiki/index.md`，純檔案處理，無外部依賴
3. **Streaming Interface**（`POST /chat/stream` + SSE）：練習 FastAPI SSE 與 token-by-token 體驗
4. **Browser UI**：搭配 stream 端點做一頁 HTML，立即可 demo
5. 其他（Multi-Format Import、CLI／MCP、Conversation Memory、Paraphrase Comparison）視時間再評估

---

## 五、切換 LLM Provider（OpenAI ↔ Google Gemini）

OpenAI 額度常常撞上限，已讓 `markdown_kb` 支援雙 provider，用環境變數切換，**OpenAI 仍是預設**。

### 怎麼切換
在 `scaffold/markdown_kb/.env` 設定（OpenAI 設定保留不動）：

```env
# 切換用：openai（預設）或 google
LLM_PROVIDER=google

# 申請：https://aistudio.google.com/apikey
GOOGLE_API_KEY=你的Google金鑰

# 可選：覆寫模型
GOOGLE_MODEL=gemini-2.5-flash
OPENAI_MODEL=gpt-4o-mini
```

- 切到 Google：`LLM_PROVIDER=google` → **重啟 server**
- 切回 OpenAI：`LLM_PROVIDER=openai`（或刪掉這行）→ 重啟 server
- 改 `.env` 後一定要**重啟 server**，因為 `get_llm()` 有快取 `_llm`

### 程式改了哪裡
- `app/retrieval.py`：`get_llm()` 依 `LLM_PROVIDER` 建立 `ChatGoogleGenerativeAI` 或 `ChatOpenAI`；錯誤訊息也會提示對應金鑰
- `requirements.txt`：新增 `langchain-google-genai==2.0.8`（已裝進 `.venv`）

### 踩過的坑（重要）
1. **模型名稱會過期**：`gemini-2.0-flash` 出現 `429 limit: 0`、`gemini-1.5-flash` 出現 `404 not found` —— 都是因為這些舊模型在現行 API 已不可用。**不是額度用完，而是模型不存在/免費層為 0**。
2. **查可用模型**（不會印出金鑰）：
   ```bash
   cd scaffold/markdown_kb
   .venv/bin/python -c "
   from dotenv import load_dotenv; load_dotenv()
   import os, google.generativeai as genai
   genai.configure(api_key=os.environ['GOOGLE_API_KEY'])
   for m in genai.list_models():
       if 'generateContent' in m.supported_generation_methods:
           print(m.name)"
   ```
3. 目前可用的 flash 系列：`gemini-flash-latest`、`gemini-2.5-flash`、`gemini-2.5-flash-lite`、`gemini-3.5-flash` 等。本專案實測 **`gemini-2.5-flash` 可正常作答**，已設為 Google 預設。

---

## 五、切換 LLM Provider（OpenAI ↔ Google Gemini）

OpenAI 額度常常撞上限，已讓 `markdown_kb` 支援雙 provider，用環境變數切換，**OpenAI 仍是預設**。

### 怎麼切換
在 `scaffold/markdown_kb/.env` 設定（OpenAI 設定保留不動）：

```env
# 切換用：openai（預設）或 google
LLM_PROVIDER=google

# 申請：https://aistudio.google.com/apikey
GOOGLE_API_KEY=你的Google金鑰

# 可選：覆寫模型
GOOGLE_MODEL=gemini-2.5-flash
OPENAI_MODEL=gpt-4o-mini
```

- 切到 Google：`LLM_PROVIDER=google` → **重啟 server**
- 切回 OpenAI：`LLM_PROVIDER=openai`（或刪掉這行）→ 重啟 server
- 改 `.env` 後一定要**重啟 server**，因為 `get_llm()` 有快取 `_llm`

### 程式改了哪裡
- `app/retrieval.py`：`get_llm()` 依 `LLM_PROVIDER` 建立 `ChatGoogleGenerativeAI` 或 `ChatOpenAI`；錯誤訊息也會提示對應金鑰
- `requirements.txt`：新增 `langchain-google-genai==2.0.8`（已裝進 `.venv`）

### 踩過的坑（重要）
1. **模型名稱會過期**：`gemini-2.0-flash` 出現 `429 limit: 0`、`gemini-1.5-flash` 出現 `404 not found` —— 都是因為這些舊模型在現行 API 已不可用。**不是額度用完，而是模型不存在/免費層為 0**。
2. **查可用模型**（不會印出金鑰）：
   ```bash
   cd scaffold/markdown_kb
   .venv/bin/python -c "
   from dotenv import load_dotenv; load_dotenv()
   import os, google.generativeai as genai
   genai.configure(api_key=os.environ['GOOGLE_API_KEY'])
   for m in genai.list_models():
       if 'generateContent' in m.supported_generation_methods:
           print(m.name)"
   ```
3. 目前可用的 flash 系列：`gemini-flash-latest`、`gemini-2.5-flash`、`gemini-2.5-flash-lite`、`gemini-3.5-flash` 等。本專案實測 **`gemini-2.5-flash` 可正常作答**，已設為 Google 預設。
4. **實測可用的備援模型**（撞上限或逾時時可換 `GOOGLE_MODEL`）：`gemini-flash-latest`、`gemini-2.5-flash-lite`、`gemini-flash-lite-latest` 皆 ✅；`gemini-3.5-flash` 曾回 504 逾時（模型忙碌，非配額問題，可重試）。
