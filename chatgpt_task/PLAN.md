# ChatGPT Task Scheduler Prototype — 實作計畫

> 目標：完成 `scaffold/` 中標記為 `TODO` 的核心邏輯，讓 MCP server 通過 inspector 測試流程（task.create → task.status → task.cancel → task.list）。

---

## 一、現況盤點

掃描 `scaffold/app/` 後，已備齊的部分與待補的部分如下：

| 檔案 | 狀態 | 需補完的內容 |
|------|------|------------|
| `app/database.py` | 完成 | SQLite engine、SessionLocal、Base |
| `app/models.py` | 完成 | `Job` model（含 `time_bucket` 欄位與 `idx_bucket_status` index）|
| `app/scheduler.py` | 部分 | `get_time_bucket()`、`find_due_jobs()` |
| `app/mcp_server.py` | 部分 | `TOOL_REGISTRY`、`route_tool_call()` |
| `requirements.txt` | 完成 | mcp / sqlalchemy 等套件 |

watcher_loop、worker_loop、MCP 註冊邏輯、tool definitions 與 handler functions 都已寫好，只需把 4 個 TODO 補完。

---

## 二、環境準備

```bash
cd scaffold
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

另外確認本機已安裝 **Node.js**（之後用 `npx` 跑 MCP inspector）。

---

## 三、實作步驟

### Step 1 — 完成 `app/scheduler.py::get_time_bucket()`

**目的**：把 `scheduled_at` 轉換成「以小時為單位」的 bucket key，當作 DB partition key 使用，watcher 才能只掃當前 bucket 而不是 full table scan。

**實作要點**：
- 使用 `strftime("%Y%m%d%H")` 把 datetime 格式化成 `"2026051512"` 這類字串。
- 回傳型別必須是 `str`（model 中欄位是 `String(10)`）。

**完成判準**：
- `get_time_bucket(datetime(2026, 5, 15, 12, 30))` 應回傳 `"2026051512"`。

---

### Step 2 — 完成 `app/scheduler.py::find_due_jobs()`

**目的**：watcher 每 10 秒呼叫一次，列出「在當前 bucket 中、已到期、且 status 仍是 pending」的 jobs。

**實作要點**：
1. 用 `get_time_bucket(current_time)` 算出當前 bucket。
2. 對 `Job` 下查詢：
   - `time_bucket == current_bucket`
   - `scheduled_at <= current_time`
   - `status == "pending"`
3. 回傳 `db.query(Job).filter(...).all()` 的結果。

**注意**：這裡只查單一 bucket 即可（簡化版）。生產環境通常會同時查「current + previous bucket」以避免邊界 race condition，原型可先不處理。

**完成判準**：
- 建立一個 `scheduled_at` 為過去時間（如 `"2025-01-01T00:00:00"`）的 job，watcher 10 秒內應抓到並丟進 queue。

---

### Step 3 — 完成 `app/mcp_server.py::TOOL_REGISTRY`

**目的**：用 dict 把 tool name 對應到 handler function，取代 if-else routing。

**實作內容**：

```python
TOOL_REGISTRY: dict = {
    "task.create": handle_create_task,
    "task.list":   handle_list_tasks,
    "task.status": handle_get_status,
    "task.cancel": handle_cancel_task,
}
```

**完成判準**：
- key 與 `TOOL_DEFINITIONS` 中四個 `Tool(name=...)` 完全一致（注意 `.` 分隔符）。

---

### Step 4 — 完成 `app/mcp_server.py::route_tool_call()`

**目的**：MCP 收到任何 tool call，都從這個單一入口 dispatch 出去。

**實作要點**：
1. `handler = TOOL_REGISTRY.get(tool_name)`
2. 若 `handler is None` → 回傳 `{"error": f"Unknown tool: {tool_name}"}`
3. 否則 → `return handler(db, **arguments)`

**陷阱提醒**：
- `handle_list_tasks` 不吃任何 argument，所以 `arguments` 為空 dict 時，`**{}` 也能正常 unpack，無需 special case。
- 不要在這層 try/except 包住整個 handler，handler 內部已自行處理 not-found 等情況；保留 exception 讓上層 `call_tool` 包裝即可。

---

## 四、本機驗證流程

### 4-1 Sanity check：直接啟動 server

```bash
python -m app.mcp_server
```

- 預期行為：process 停在等 stdin 的狀態（這就是 stdio MCP server 的正常表現）。
- 用 `Ctrl+C` 結束。
- 若出現 `ImportError` 或其他 crash，先修掉再進下一步。

### 4-2 用 MCP inspector 跑互動測試

```bash
npx @modelcontextprotocol/inspector python -m app.mcp_server
```

瀏覽器會開啟 `http://localhost:5173`，依序操作：

| # | 操作 | 預期結果 |
|---|------|---------|
| 1 | 點 **Connect** | tool list 顯示 4 個工具：`task.create` / `task.list` / `task.status` / `task.cancel` |
| 2 | `task.create`：`description="Summarize tech news"`、`scheduled_at=<當前小時內的過去時間>`（見下方 ⚠） | 回傳 `{"job_id": 1, "status": "pending", ...}` |
| 3 | 等約 10 秒後 → `task.status` 帶 `job_id=1` | status 變成 `"completed"` |
| 4 | `task.create` 帶未來時間 `"2099-12-31T00:00:00"` | 拿到 `job_id=2` |
| 5 | `task.cancel` 帶 `job_id=2` | status 變成 `"cancelled"` |
| 6 | `task.list` | 看到上述所有 jobs |

任何一步失敗就回頭檢查對應 TODO 是否正確。

> ⚠ **與 PROMPT.md 的差異**：PROMPT.md 示範用 `scheduled_at="2025-01-01T00:00:00"`，但我們的 `find_due_jobs()` 採嚴格 partition pruning（`time_bucket == current_bucket`），歷史 bucket 的 job 不會被掃到 — 這是 partition 的設計本意。實測時要用「**當前小時內、但已過的時間**」，例如現在是 `2026-05-15 14:30`（UTC），就填 `"2026-05-15T14:00:00"`。可先用 `date -u +"%Y-%m-%dT%H:00:00"` 取當前 UTC 小時起點。

---

## 五、Troubleshooting Checklist

| 症狀 | 可能原因 | 處置 |
|------|---------|------|
| inspector 顯示 0 個 tool | `TOOL_REGISTRY` 為空 / key 名稱拼錯 | 對齊 `TOOL_DEFINITIONS` 中四個 name |
| 過期 job 一直停在 `pending` | `get_time_bucket()` 沒回傳字串、或 `find_due_jobs()` 沒篩 `status=="pending"` | 用 print/logger 印出當前 bucket 與 query 結果 |
| `task.cancel` 失敗 | 已經被 worker 跑完進到 `completed`/`failed` | 改測未來時間的 job |
| `chatgpt_task.db` 累積太多舊資料污染測試 | SQLite 檔殘留 | 直接刪 `scaffold/chatgpt_task.db` 後再啟動 |
| 同一秒內 watcher 重複抓同一個 job | watcher 還沒把 status 改成 `queued` 前又掃到 | 已透過 `job.status = "queued"; db.commit()` 處理，正常情況不會發生 |

---

## 六、（可選）連到 Claude Desktop / Claude Code

inspector 全綠後再做。設定檔位置：

- **Claude Desktop**：`~/Library/Application Support/Claude/claude_desktop_config.json`
- **Claude Code**：`~/.claude.json`（top-level `mcpServers`）

設定區塊（路徑要用**絕對路徑**）：

```json
{
  "mcpServers": {
    "task-scheduler": {
      "command": "/absolute/path/to/scaffold/.venv/bin/python",
      "args": ["-m", "app.mcp_server"],
      "cwd": "/absolute/path/to/scaffold"
    }
  }
}
```

完整重啟 Claude Desktop 後，輸入框的 🔨 圖示應顯示 4 個 tool。對 Claude 說：

> 「Schedule a task to review PR #123 tomorrow at 9am.」

Claude 會呼叫 `task.create` 並回傳 `job_id`。

---

## 七、（可選）Bonus Challenges

完成主線後可挑：
- 接真 LLM 解析自然語言 task description，再呼叫 `task.create`。
- 支援 cron 表達式做 recurring jobs。
- Job chaining：A 完成 → 自動觸發 B。
- 加 MCP `resources` 支援（把 job 細節變成 readable resource）。
- 加 MCP `prompts` 支援（如 `daily_review` prompt template）。

---

## 八、Definition of Done

- [x] `get_time_bucket()` 回傳正確的 hourly bucket 字串
- [x] `find_due_jobs()` 能撈到當前 bucket、到期、pending 的 jobs
- [x] `TOOL_REGISTRY` 含 4 個 key
- [x] `route_tool_call()` 能正確 dispatch、未知工具回 error
- [x] server 啟動 sanity check 通過（`python -m app.mcp_server` 正常 hang on stdin）
- [x] inspector 六步驟測試全部通過
- [x] 可成功 cancel 一個未來 job
- [x] `task.list` 能看到全部 job 與其最終 status

---

## 九、進度記錄

| 日期 | 步驟 | 備註 |
|------|------|------|
| 2026-05-15 | 環境修復 | macOS 26.2 的 brew Python 3.12 `pyexpat.so` 載入失敗 → `brew install expat` + `install_name_tool` 改指 brew expat + 重新 `codesign -s -` 簽章 |
| 2026-05-15 | Step 1 完成 | `get_time_bucket()` 用 `strftime("%Y%m%d%H")` 實作，4 個邊界 case 通過 |
| 2026-05-15 | Step 2 完成 | `find_due_jobs()` 以 `time_bucket == current_bucket AND scheduled_at <= now AND status == "pending"` 實作，6 個 case 通過 |
| 2026-05-15 | Step 3 完成 | `TOOL_REGISTRY` 映射 4 個 `task.*` name → handler |
| 2026-05-15 | Step 4 完成 | `route_tool_call()` 以 `TOOL_REGISTRY.get()` dispatch，未知工具回 error；端對端 create→status→list→cancel→unknown→missing-job 全綠 |
| 2026-05-15 | server sanity | `python -m app.mcp_server` 啟動後正常 hang on stdin（用 fifo 保持 stdin 開啟驗證）|
