# Knowledge Base Q&A Bot 實作計畫（Vector RAG 版）

> 目標：基於 `scaffold/vector_rag`（Strategy B: Vector RAG）完成可通過 `PROMPT.md` 中所有 `curl` 驗證的 Q&A bot。
> 與 `PLAN.md`（Strategy A: Markdown KB / BM25）平行，本檔案聚焦在 embeddings + FAISS 路線的「實作」與「驗證」。

---

## 〇、與 Markdown KB 版的核心差異

| 面向 | Strategy A（Markdown KB / `PLAN.md`） | Strategy B（Vector RAG / 本檔） |
| --- | --- | --- |
| 檢索單位 | heading section | chunk（section 再切 ~500 字） |
| 檢索方式 | BM25 關鍵字打分（純本地） | embedding 語意相似度（FAISS） |
| 索引產物 | `.kb/index.json`（可讀） | `.kb/faiss_index/`（二進位 + `metadata.json`） |
| `/index` 是否要打 API | 否 | **是**，要呼叫 OpenAI embeddings 把每個 chunk 向量化 |
| `/chat` 是否要打 embeddings | 否 | **是**，query 也要先 embed 才能搜尋 |
| 對 `OPENAI_API_KEY` 依賴 | 只有生成答案需要 | **索引、查詢、生成都需要** |
| 同義詞/換句話 | 容易 miss | 語意檢索通常較強 |

> 重點心智模型：BM25 是「字面對得上才有分」；Vector RAG 是「意思接近就會被撈出來」。代價是每次 index/query 都要打 embedding API、且索引不可讀。

---

## 一、現況盤點

- `docs/` 已含三份 Markdown：`refund_policy.md`、`account_help.md`、`shipping_faq.md`（與 A 版共用同一份 docs）
- `scaffold/vector_rag/app/` 已有骨架，待實作的 `TODO`：
  - `indexer.py`：`load_markdown_sections`、`build_index`、`save_vector_index`、`load_vector_index`
  - `retrieval.py`：`SYSTEM_PROMPT`、`build_prompt`
- 已就緒、不需改的部分：
  - `indexer.py`：`slugify`、`get_embeddings`（已含 `OPENAI_API_KEY` 檢查）、`search`（`similarity_search_with_score`）
  - `retrieval.py`：`get_llm`、`query`（已串好 vectorstore 判空、search、組 sources）
  - `main.py`（startup 呼叫 `load_vector_index`）、`routes.py`（`/health`、`/index`、`/chat`）、`schemas.py`
- 既有常數：`DOCS_DIR`、`INDEX_DIR=.kb/faiss_index`、`EMBEDDING_MODEL="text-embedding-3-small"`、`HEADING_RE`、`splitter`（`chunk_size=500, chunk_overlap=0`）

> 注意：`INDEX_DIR` 與 A 版 `.kb/index.json` 同住在 `.kb/` 下，但**檔名不衝突**（一個是 `index.json`，一個是 `faiss_index/` 目錄），兩種策略可並存。

---

## 二、實作步驟（依執行順序）

### Step 1. 環境準備
- [x] 進入 `scaffold/vector_rag/`
- [x] 建立**獨立**虛擬環境並安裝 `requirements.txt`（含 `faiss-cpu`、`langchain-openai`，與 A 版的 venv 分開以免套件互相干擾）
- [x] `export OPENAI_API_KEY="sk-..."`（embeddings + 生成都要用，必填）—— 本機改用 `.env` + `load_dotenv()`，見下方註記
- [x] 試跑 `uvicorn app.main:app --reload --port 8000`，確認 `/health` 回 `{"status":"ok"}`

> **實作過程踩到的環境坑（重要）**
> 1. **Python 3.14 + faiss**：本機是 Python 3.14.3，`faiss-cpu==1.9.0.post1` 沒有對應 wheel（最低 1.12.0）。已把 `requirements.txt` 改成 `faiss-cpu==1.12.0`。
> 2. **`.env` 自動載入**：原 scaffold 的 `main.py` 沒有 `load_dotenv()`，`requirements.txt` 也沒列 `python-dotenv`，所以 `.env` 不會被讀到。已補 `python-dotenv` 並在 `main.py` 加 `load_dotenv()`（與 A 版一致），直接複用 A 版的 `.env`。
> 3. **OpenAI 額度撞牆**：實測 `OPENAI_API_KEY` 回 `429 insufficient_quota`，embeddings 完全跑不動。已比照 A 版 `get_llm()` 把 **embeddings 與生成都加上 Google fallback**（見第五節），實測以 `LLM_PROVIDER=google` 全程驗證通過。
  - 第一次設定：
  ```bash
    # 1. 進到 scaffold/vector_rag（uvicorn 要在這層跑）
    cd /Users/jess/Documents/build-moat-live-sessions/knowledge_base_qa_bot/scaffold/vector_rag

    # 2. 建虛擬環境（只做一次）
    python3 -m venv .venv

    # 3. 啟動 venv（每次新開 terminal 都要）
    source .venv/bin/activate

    # 4. 安裝套件（只做一次，或 requirements.txt 改了再做）
    pip install -r requirements.txt

    # 5. 設定金鑰（embeddings 也吃這把）
    export OPENAI_API_KEY="sk-..."

    # 6. 跑 server
    uvicorn app.main:app --reload --port 8000
  ```
  - 重新啟動 server 時：
  ```bash
    cd /Users/jess/Documents/build-moat-live-sessions/knowledge_base_qa_bot/scaffold/vector_rag
    source .venv/bin/activate
    export OPENAI_API_KEY="sk-..."   # 若未寫進 .env
    uvicorn app.main:app --reload --port 8000
  ```

### Step 2. 實作 `indexer.load_markdown_sections(path) -> list[Document]`
> 目的：把單一 `.md` 切成「帶 source 的 heading section」，之後再交給 `splitter` 切 chunk。對齊 A 版的 `parse_markdown`，但回傳的是 LangChain `Document`。
- [x] 用 `HEADING_RE` 逐行偵測 `#` 標題，切出每個 heading section
- [x] 維護 `heading_path`（堆疊各層 heading，從 `#` 到 `######`），供引用顯示與檢索語境
- [x] 每個 section 產出 `Document`：
  - `page_content`：**把 `heading_path` 與 content 一起放進去**（heading 文字也是重要語意訊號，能提升召回）
  - `metadata = {"source": f"{path.name}#{slugify(heading)}", "heading": " > ".join(heading_path)}`
    - `source` 例：`refund_policy.md#refund-timeline`（這就是引用 ID）
- [x] 文件開頭非 heading 內容：略過或併入第一個 section（擇一即可，與 A 版一致）

### Step 3. 實作 `indexer.build_index(docs_dir) -> tuple[int, int]`
- [x] 掃 `docs_dir.glob("*.md")`，對每檔呼叫 `load_markdown_sections`，合併成 `all_sections`
- [x] `files_indexed = 掃到的檔數`
- [x] 用 `splitter.split_documents(all_sections)` 把 section 再切成 chunks（會沿用每個 section 的 metadata）
- [x] `vectorstore = FAISS.from_documents(chunks, get_embeddings())`（這步會打 OpenAI embeddings）
- [x] 設定 `sections_indexed = len(chunks)`（注意：這裡的「sections」語意上其實是 chunk 數，schema 欄位名沿用 `sections_indexed`）
- [x] 呼叫 `save_vector_index()` 持久化
- [x] 回傳 `(files_indexed, sections_indexed)`
- 邊界：docs 為空 → `vectorstore=None`、回 `(0, 0)`，且不要寫出殘缺索引（見 Step 4 的清理）

### Step 4. 實作 `indexer.save_vector_index(index_dir)`
- [x] `vectorstore is None` 或 `sections_indexed == 0` → 用 `shutil.rmtree(index_dir, ignore_errors=True)` 清掉舊的殘留索引後 `return`（避免重啟時載到過時索引）
- [x] `index_dir.mkdir(parents=True, exist_ok=True)`
- [x] `vectorstore.save_local(str(index_dir))`（產生 `index.faiss` + `index.pkl`）
- [x] 另寫 `metadata.json`（`indent=2`，方便 `cat` 檢視，也對應 `PROMPT.md` 的驗證）：
  ```json
  {
    "embedding_model": "text-embedding-3-small",
    "files_indexed": 3,
    "sections_indexed": <chunks>
  }
  ```

### Step 5. 實作 `indexer.load_vector_index(index_dir) -> tuple[int, int]`
> startup 時被呼叫；目的：重啟後**不需要重新 embedding** 就能直接 `/chat`。
- [x] 若 `index.faiss` 或 `index.pkl` 不存在 → 回 `(0, 0)`（維持未索引狀態）
- [x] 讀 `metadata.json`，**比對 `embedding_model` 是否仍等於 `EMBEDDING_MODEL`**；不符就放棄載入並回 `(0, 0)`（換了 embedding 模型則舊向量不可用，需重新 `/index`）
- [x] `vectorstore = FAISS.load_local(str(index_dir), get_embeddings(), allow_dangerous_deserialization=True)`
  - ⚠️ `allow_dangerous_deserialization=True` 只因為這個索引是本機 app 自己產生的；切勿載入來路不明的 `index.pkl`
- [x] 還原 `files_indexed` / `sections_indexed`（從 metadata 讀），回傳 `(files_indexed, sections_indexed)`

### Step 6. 實作 `retrieval.SYSTEM_PROMPT`
> 規則與 A 版**完全相同**（hallucination 防線），可直接沿用 `PLAN.md` Step 7 的 prompt。
- [x] 限定「只根據 CONTEXT 回答」
- [x] 引用格式必須是 `[Source: filename#heading]`，且只能引用 CONTEXT 內出現過的 ID
- [x] 缺資訊時回 `I cannot confirm from the knowledge base.`
- [x] 嚴禁猜測或使用外部知識
- 提示：可直接把 A 版 `markdown_kb/app/retrieval.py` 的 `SYSTEM_PROMPT` 複製過來，兩策略共用同一套引用契約

### Step 7. 實作 `retrieval.build_prompt(query, ranked_chunks) -> str`
> `ranked_chunks` 是 `search()` 回傳的 `list[(Document, score)]`。
- [x] 對每個 `(doc, score)`，輸出格式：
  ```
  [Source: <doc.metadata["source"]>]
  Heading path: <doc.metadata["heading"]>
  <doc.page_content>
  ```
- [x] score/distance 可選擇性附上，但**僅供 debug**，別讓模型把分數寫進答案
- [x] 全部組成 `CONTEXT:\n...\n\nQUESTION:\n<query>`（CONTEXT 在前、QUESTION 在後）

### Step 8.（建議）加 Score Threshold（對應 Stretch Goal）
> FAISS `similarity_search_with_score` 回的是**距離（L2，越小越近）**，與 BM25 的「越大越好」相反，要小心方向。
- [x] 在 `retrieval.query` 取得 `ranked_chunks` 後，檢查最佳（最小距離）是否超過門檻
- [x] 全部太遠（距離過大）→ 直接回 `I cannot confirm from the knowledge base.`，不要硬湊引用
- [x] 門檻需實測 calibrate（`text-embedding-3-small` 的 L2 距離量級需用真實 query 觀察後再定）

### Step 9. 重啟驗證持久化
- [x] `POST /index` 後檢查 `.kb/faiss_index/` 是否生成 `index.faiss`、`index.pkl`、`metadata.json`
- [x] 停掉 server，重新啟動後**不呼叫** `/index`，直接 `/chat`，應由 startup 的 `load_vector_index()` 載回索引並正常作答

---

## 三、Verification Checklist（對應 `PROMPT.md`）

依序執行並保留輸出：

- [x] `curl http://localhost:8000/health` → `{"status":"ok"}`
- [x] 未 index 前 `POST /chat` → 提示「knowledge base has not been indexed yet」
  ```bash
  # 先清掉持久化索引再重啟，才能重現「未 index」狀態：
  rm -rf /Users/jess/Documents/build-moat-live-sessions/knowledge_base_qa_bot/.kb/faiss_index
  ```
- [x] `POST /index` → `{"files_indexed": 3, "sections_indexed": M}`（M = chunk 數，依 chunk_size 而定）
- [x] `cat .kb/faiss_index/metadata.json` → 看到 `embedding_model` / `files_indexed` / `sections_indexed`
- [x] 重啟 server，未再呼叫 `/index`，可直接 `/chat`（驗證 startup 載入）
- [x] 問「How long do refunds take?」→ 引用 `refund_policy.md#refund-timeline`
- [x] 問「Can I change my email address?」→ 引用 `account_help.md#change-email-address`
- [x] 問「Which restaurants are nearby?」→ 回 `cannot confirm from the knowledge base`

---

## 四、（選做）Stretch Goals 優先順序

1. **Score Threshold and Fallback**（已併入 Step 8）：距離門檻 fallback，最容易做且擋掉語意 false positive
2. **Paraphrase Comparison**：對同一批換句話 query，比較本 Vector RAG 與 A 版 Markdown KB 的召回/引用品質——這正是 Vector RAG 最能展現價值的地方（同義詞、換句話）
3. **Streaming Interface**（`POST /chat/stream` + SSE）：先回 sources 再 stream token，最後 `done` event
4. **Browser UI**：搭配 stream 端點做一頁 HTML
5. 其他（Multi-Format Import、CLI／MCP、Wiki/Answer Filing、Conversation Memory）視時間再評估

---

## 五、切換 Provider（OpenAI ↔ Google）— 已實作

A 版只需切換「生成用 LLM」，Vector RAG 多了一層 **embedding**，所以**兩處都做了雙 provider**，用同一個 `LLM_PROVIDER` 環境變數一起切（OpenAI 仍為預設）：

- `retrieval.get_llm()`：依 `LLM_PROVIDER` 建 `ChatGoogleGenerativeAI`（`GOOGLE_MODEL`，預設 `gemini-2.5-flash`）或 `ChatOpenAI`（`OPENAI_MODEL`，預設 `gpt-4o-mini`）—— 與 A 版相同
- `indexer.get_embeddings()`：依 `LLM_PROVIDER` 建 `GoogleGenerativeAIEmbeddings`（`GOOGLE_EMBEDDING_MODEL`，預設 `models/gemini-embedding-001`，dim 3072）或 `OpenAIEmbeddings`（`OPENAI_EMBEDDING_MODEL`，預設 `text-embedding-3-small`）
- `indexer.embedding_model_id()`：回傳 `"<provider>:<model>"`（例：`google:models/gemini-embedding-001`），寫進 `metadata.json` 的 `embedding_model`

### 怎麼切換
在 `scaffold/vector_rag/.env` 設定後**重啟 server**：
```env
LLM_PROVIDER=google          # openai（預設）或 google
GOOGLE_API_KEY=你的Google金鑰
# 可選覆寫：
GOOGLE_MODEL=gemini-2.5-flash
GOOGLE_EMBEDDING_MODEL=models/gemini-embedding-001
```

### ⚠️ embedding 不可混用（核心鐵則）
索引用哪個模型 embed，查詢就**必須**用同一個。換 provider／換 embedding 模型 → 維度與向量空間全變，舊 `.kb/faiss_index/` 整個作廢。`load_vector_index()` 比對 `embedding_model_id()` 就是在守這條：不符會直接回 `(0,0)` 不載入。

切換 embedding 設定後一律：**刪 `.kb/faiss_index/` → 重啟 → 重新 `/index`**：
```bash
rm -rf /Users/jess/Documents/build-moat-live-sessions/knowledge_base_qa_bot/.kb/faiss_index
```

### 實測（OpenAI 額度撞牆 → 走 Google）
- `OPENAI_API_KEY` 回 `429 insufficient_quota`，OpenAI embeddings 完全不能用
- 設 `LLM_PROVIDER=google` 後，embeddings（`gemini-embedding-001`, dim 3072）與生成（`gemini-2.5-flash`）全程通過 `PROMPT.md` 所有驗證
- 可用的 Google embedding 模型（`embedContent`）：`models/gemini-embedding-001`、`models/gemini-embedding-2`、`models/gemini-embedding-2-preview`

> 註：第三節 checklist 與 Step 4 範例中的 `metadata.json` 寫 `text-embedding-3-small` 是 OpenAI 預設情境的示意；實測走 Google 時實際存的是 `google:models/gemini-embedding-001`。
