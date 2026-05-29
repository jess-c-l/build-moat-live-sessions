# Knowledge Base Q&A Bot 系統流程

> 對應實作：`scaffold/markdown_kb/`
> 對應計畫：[PLAN.md](./PLAN.md)
> 對應設計：[DESIGN_ANS.md](./DESIGN_ANS.md)

---

## 1. 系統定位

一個基於 Markdown 檔案的 Q&A bot：

- **輸入**：使用者自然語言問題
- **檢索**：BM25 對 Markdown sections 做 keyword search
- **生成**：把 top-k sections 餵給 LLM，限定它只能根據 CONTEXT 回答並引用 source
- **輸出**：含 `[Source: filename#heading]` 的回答 + 可檢視的 sources 列表

---

## 2. 持久層概觀

```
┌──────────────────────────────────────────────────────────────────────┐
│                         FILE SYSTEM                                  │
│                                                                      │
│   docs/                          .kb/                                │
│   ├── refund_policy.md           └── index.json                      │
│   ├── account_help.md                (sections + stats)              │
│   └── shipping_faq.md                                                │
└──────────────────────────────────────────────────────────────────────┘
            ↑ 來源（人類維護）           ↑ 派生（程式產生，可重建）
```

- `docs/*.md` 是 single source of truth，由人類編輯。
- `.kb/index.json` 是派生產物，由 `POST /index` 產生，git 通常 ignore。
- Server 進程內的 `indexer.sections` 是 in-memory 結構，重啟後消失，由 startup 從 `.kb/index.json` rehydrate。

---

## 3. Server 啟動流程

```
uvicorn app.main:app
   │
   ├─ load_dotenv()                     讀 .env（OPENAI_API_KEY）
   ├─ FastAPI() + include_router        掛上 /health, /index, /chat
   │
   └─ @startup event
         │
         └─ load_index_json()
              │
              ├─ 檢查 .kb/index.json 是否存在
              │     不存在 → return (0, 0)   ← 第一次啟動會走這
              │     存在   → 讀 JSON → 還原 Section dataclasses
              │
              └─ indexer.sections = [Section, Section, ...]
                 rebuild_stats()             重算 doc_freq / avg_doc_len
```

**重點**：`sections` 是 module-level global，整個 server 進程共用。startup 把它從磁碟還原回記憶體；之後所有請求都讀這份 in-memory 結構，不會再碰 `docs/`。

---

## 4. `POST /index`：建立索引

文件改了或第一次部署時呼叫一次。

```
curl -X POST http://localhost:8000/index
   │
   ▼
routes.index_docs()
   │
   └─ build_index()
        │
        ├─ for md in docs/*.md:
        │     parse_markdown(md)
        │        ├─ HEADING_RE 切 sections
        │        ├─ 維護 heading_stack → heading_path
        │        └─ tokenize(heading + content)
        │     → return [Section, Section, ...]
        │
        ├─ indexer.sections = 全部合併       取代記憶體
        │
        ├─ rebuild_stats()
        │     ├─ files_indexed = len({s.file for s in sections})
        │     ├─ doc_freq[t] += 1  for t in set(s.tokens)
        │     └─ avg_doc_len = mean(len(s.tokens))
        │
        └─ write_index_json()
              └─ .kb/index.json ← {"sections":[...], "stats":{...}}

   ▼
response: {"files_indexed": 3, "sections_indexed": 12}
```

---

## 5. `POST /chat`：問答主流程

```
curl -X POST http://localhost:8000/chat \
     -d '{"query":"How long do refunds take?"}'
   │
   ▼
routes.chat(req)
   │
   └─ retrieval.query("How long do refunds take?")
        │
        ├─ if not indexer.sections:
        │     return "knowledge base 尚未 index"      ← 還沒跑 /index 時走這
        │
        ├─ indexer.search(question, k=3)              檢索 top-3 sections
        │     │
        │     ├─ query_tokens = tokenize("how long do refunds take")
        │     │                = ["long", "refunds", "take"]   (stopwords 過濾)
        │     │
        │     ├─ for section in sections:
        │     │     score = bm25_score(query_tokens, section)
        │     │           = Σ (idf(t) × tf-normalized(t, section))
        │     │           + heading_boost
        │     │
        │     └─ 排序、取前 3、過濾 score > 0
        │
        ├─ if not ranked:
        │     return "I cannot confirm from the knowledge base."
        │
        ├─ build_prompt(question, ranked)
        │     ┌─────────────────────────────────────┐
        │     │ CONTEXT:                            │
        │     │ [Source: refund_policy.md#refund-…] │
        │     │ Heading path: Refund Policy > …     │
        │     │ Approved refunds are processed …    │
        │     │                                     │
        │     │ [Source: …]                         │
        │     │ …                                   │
        │     │                                     │
        │     │ QUESTION:                           │
        │     │ How long do refunds take?           │
        │     └─────────────────────────────────────┘
        │
        ├─ get_llm().invoke([
        │       SystemMessage(SYSTEM_PROMPT),
        │       HumanMessage(prompt)
        │   ])
        │     │
        │     └→ OpenAI API（gpt-4o-mini）
        │           回 "Approved refunds are processed within 5-7
        │              business days. [Source: refund_policy.md#refund-timeline]"
        │
        └─ 組裝 response
              {
                "answer": LLM 回答,
                "sources": [
                  {
                    "source": "refund_policy.md#refund-timeline",
                    "heading": "Refund Policy > Refund Timeline",
                    "score": 2.41,
                    "content": "Approved refunds are processed within..."
                  },
                  ...
                ]
              }
```

---

## 6. 模組責任分工

| 檔案 | 角色 |
| --- | --- |
| `app/main.py` | FastAPI app 組裝 + startup hook |
| `app/routes.py` | HTTP 層：URL → 呼叫對應 function |
| `app/indexer.py` | **檢索層**：parse / index / persist / BM25 score / search |
| `app/retrieval.py` | **生成層**：SYSTEM_PROMPT / build_prompt / 呼叫 LLM |
| `app/schemas.py` | Pydantic request/response models |

`retrieval.py` 透過 `indexer.search()` 拿到 ranked sections，自己不碰索引內部狀態。
這層分離讓你日後可以把 `indexer` 換成 vector store（見 DESIGN_ANS 的切換情境），
`retrieval.py` 不用大改。

---

## 7. 三條資料生命週期

```
docs/*.md           ← 人類編輯
    │
    │ POST /index（手動觸發）
    ▼
.kb/index.json      ← 派生產物，可隨時重建
    │
    │ server startup（自動）
    ▼
indexer.sections    ← in-memory，server 重啟後消失
    │
    │ POST /chat（每次請求）
    ▼
LLM answer
```

**設計意涵**：

- 文件改了 → 重跑 `POST /index`（不需要重啟 server）
- Server 重啟 → 自動從 `.kb/index.json` 還原，**不必重跑 `/index`**
- 想完全重建 → 刪掉 `.kb/index.json` 再跑 `/index`

---

## 8. 關鍵資料結構

### `Section`（`indexer.py`）

```python
@dataclass
class Section:
    id: str                # "refund_policy.md#refund-timeline"
    file: str              # "refund_policy.md"
    heading: str           # "Refund Timeline"
    heading_path: list[str]# ["Refund Policy", "Refund Timeline"]
    content: str           # heading 之後到下個 heading 之前的內文
    tokens: list[str]      # tokenize(heading + " " + content)
```

### Module-level globals（`indexer.py`）

| 變數 | 型別 | 來源 |
| --- | --- | --- |
| `sections` | `list[Section]` | `build_index()` 或 `load_index_json()` |
| `doc_freq` | `Counter[str]` | `rebuild_stats()` |
| `avg_doc_len` | `float` | `rebuild_stats()` |
| `files_indexed` | `int` | `rebuild_stats()` |

### 索引檔（`.kb/index.json`）

```json
{
  "sections": [
    {
      "id": "refund_policy.md#refund-timeline",
      "file": "refund_policy.md",
      "heading": "Refund Timeline",
      "heading_path": ["Refund Policy", "Refund Timeline"],
      "content": "Approved refunds are processed within ...",
      "tokens": ["refund", "timeline", "approved", "refunds", ...]
    }
  ],
  "stats": {
    "files_indexed": 3,
    "avg_doc_len": 13.83
  }
}
```

註：`doc_freq` 故意不寫進 JSON，因為它能從 `sections` 在 `rebuild_stats()` 重算，避免重複資料造成 inconsistency。

---

## 9. 失敗路徑（fallback 行為）

| 情境 | 行為 | 回應 |
| --- | --- | --- |
| `.kb/index.json` 不存在 | `load_index_json` return `(0,0)`，sections 留空 | startup 不報錯 |
| `sections` 為空時收到 `/chat` | 不呼叫 LLM | `"knowledge base 尚未 index"` |
| BM25 全部 0 分（query 無 match） | `search()` 過濾 `score > 0` 後為空 | `"I cannot confirm from the knowledge base."` |
| LLM 拿到 CONTEXT 但仍找不到答案 | 由 `SYSTEM_PROMPT` 規範 | 同上 fallback 句 |

---

## 10. 與 `PROMPT.md` 驗收項對照

| Verification | 對應流程 |
| --- | --- |
| `GET /health` → `{"status":"ok"}` | §3 startup（無 index 也能 health） |
| 未 index 前 `POST /chat` 提示 | §9 fallback 第二列 |
| `POST /index` → `{"files_indexed":3,"sections_indexed":N}` | §4 |
| `cat .kb/index.json` | §4 最後一步 |
| 重啟後直接 `/chat` | §3 startup 載入 |
| Refund / Email 問題正確引用 | §5 整條 |
| 「Which restaurants are nearby?」回 fallback | §9 fallback 第三列 |
