# Test Results — Markdown KB vs Vector RAG

> 測試日期：2026-05-29 ｜ Provider：`LLM_PROVIDER=google`（生成 `gemini-2.5-flash`，embedding `models/gemini-embedding-001`）
> 跑法：markdown_kb 在 :8001、vector_rag 在 :8002，各自獨立 venv；`time` 取 `curl` 的 `time_total`（端到端）。
> 知識庫：`docs/` 三檔（`refund_policy.md`、`account_help.md`、`shipping_faq.md`），索引單位 = heading section，兩邊都切出 `files=3, sections/chunks=12`。

---

## 一、逐項測試對照

| # | 測試 | 預期 | Markdown KB（:8001） | Vector RAG（:8002） |
| --- | --- | --- | --- | --- |
| 1 | 未 index 先 `/chat` | 提示尚未建索引 | ✅ "has not been indexed yet" / **0.0018s** | ✅ 同上 / **0.0018s** |
| 2 | `POST /index` | `{files:3, sections:12}` | ✅ `{3,12}` / **0.0038s**（純本地） | ✅ `{3,12}` / **1.821s**（打 embedding API） |
| 3 | 檢視持久化索引 | 可讀 | ✅ `.kb/index.json` 純文字、tokens 可讀 | ✅ `.kb/faiss_index/`：`index.faiss`＋`index.pkl`＋`metadata.json`（二進位，僅 metadata 可讀） |
| 4 | 重啟後不 `/index` 直接問退款 | 引用 `refund_policy.md#refund-timeline` | ✅ 命中、正確引用 / **2.337s** | ✅ 命中、正確引用 / **2.994s** |
| 5 | 改 email | 引用 `account_help.md#change-email-address` | ✅ 命中、正確引用 / **1.678s** | ⚠️ 檢索命中（dist 0.511 排第一），但**生成撞 429 額度** / 2.862s |
| 6 | 範圍外（餐廳） | 回 "cannot confirm" | ✅ "I cannot confirm…" / **0.0013s**（BM25=0，**未呼叫 LLM**） | ⚠️ 檢索回最近鄰（dist ≥0.83），**生成撞 429** / 2.884s |
| 7 | 額外：改 email 到 jess@gmail.com | 引用 change-email-address | ✅ 命中、正確引用 / **2.643s** | ⚠️ 檢索命中（dist 0.536 排第一），**生成撞 429** / 2.980s |

> ⚠️ Vector 第 5–7 題的失敗**不是程式 bug**：Google 免費額度（generate_content 每日 20 次、每分鐘 5 次）被當天反覆測試耗盡，回 `ResourceExhausted: 429`。**檢索層（embedding + FAISS）全數成功並正確排序**（見每題 `sources`），失敗只發生在最後的 LLM 生成步驟。這本身就印證了「檢索與生成都綁外部 API 額度」的代價。

---

## 二、延遲拆解（呼應「執行時間差不多」的觀察）

| 操作 | Markdown KB | Vector RAG | 差異與原因 |
| --- | --- | --- | --- |
| `/index` 建索引 | **0.0038s** | **1.821s** | **約 480×**。Vector 要對 12 個 chunk 逐一打 embedding API；Markdown 純本地 tokenize。 |
| 範圍外 query（餐廳） | **0.0013s** | ~2.88s | Markdown BM25 分數=0 → **短路、根本不呼叫 LLM**；Vector 語意檢索永遠找得到最近鄰，仍走 query-embedding（+生成）。 |
| 命中 query（退款/email） | 1.7–2.6s | 2.9–3.0s | **這裡才是「差不多」的來源**：兩者都被 LLM 生成那 ~2s 主宰，Vector 只多一段 query embedding 往返（約 +0.3–0.5s），體感接近。 |

**結論**：所謂「跑起來差不多」只成立於「命中題的端到端時間」，因為 LLM 生成蓋過一切。一旦看 `/index` 與範圍外題，差距是數百倍——而且 Vector **沒有一處比 Markdown 快**（命中題還略慢）。

---

## 三、印證「embedding 是外部 API 依賴」

| 步驟 | Markdown KB | Vector RAG | 證據 |
| --- | --- | --- | --- |
| 建索引 | 純本地 | **打 embedding API** | `/index` 0.0038s vs 1.821s |
| 查詢檢索 | 純本地 BM25 | **query 先 embed 才能搜** | 範圍外題 0.0013s vs 2.88s（前者完全沒碰 API） |
| 生成答案 | 需 API | 需 API | 兩邊都受 429 額度影響 |
| 額度風險面 | **僅生成 1 處** | **index＋query＋生成 3 處** | Vector 第 5–7 題：檢索成功、生成被額度打掛 |

> 一句話：**Vector RAG 把「檢索」也變成外部 API 依賴**，多了 embedding 這層額度/延遲/成本風險面；Markdown KB 的檢索全本地，唯一的 API 風險集中在最後生成。在這個小型、結構化知識庫，這個多出來的依賴換不到對等好處（速度沒贏、召回也夠），所以選 Markdown KB。

---

## 四、檢索品質旁註（兩邊都對）

- 兩種策略在命中題都把**正確 section 排在第一**：
  - 退款題 → `refund_policy.md#refund-timeline`（BM25 與 FAISS 皆 top-1）
  - email 題 → `account_help.md#change-email-address`（BM25 score 11.2／FAISS distance 0.511，皆 top-1）
- 分數方向相反，別看錯：**BM25 越大越相關**；**FAISS 是 L2 距離、越小越相關**。
- 範圍外題：Markdown 直接 score=0 短路；Vector 仍回最近鄰（distance ≥0.83），需靠 score threshold／SYSTEM_PROMPT 擋下（本次因額度未能驗證生成端的 fallback 文字）。

---

## 五、原始輸出存檔

- Markdown KB：`/tmp/md_results.txt`
- Vector RAG：`/tmp/vec_results.txt`
- 測試腳本：`/tmp/test_kb.sh`
