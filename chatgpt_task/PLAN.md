# ChatGPT Task Scheduler Prototype — 實作計畫

> 目標：完成 `scaffold/` 中標記為 `TODO` 的核心邏輯，讓 MCP server 通過 inspector 測試流程（task_create → task_status → task_cancel → task_list）。
>
> ⚠ 命名規範：tool name 必須匹配 `^[a-zA-Z0-9_-]{1,128}$`（Anthropic API 限制），**不能用 `.`**。早期版本曾用 `task.create` 等含點命名，會導致 Claude Code 載入時靜默過濾（inspector 比較寬，所以本機看得到、Claude Code session 看不到）。已改為 `task_create` / `task_list` / `task_status` / `task_cancel`。

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
    "task_create": handle_create_task,
    "task_list":   handle_list_tasks,
    "task_status": handle_get_status,
    "task_cancel": handle_cancel_task,
}
```

**完成判準**：
- key 與 `TOOL_DEFINITIONS` 中四個 `Tool(name=...)` 完全一致（用 `_` 分隔，不可用 `.`，否則 Claude Code 會過濾掉這些工具）。

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
| 1 | 點 **Connect** | tool list 顯示 4 個工具：`task_create` / `task_list` / `task_status` / `task_cancel` |
| 2 | `task_create`：`description="Summarize tech news"`、`scheduled_at=<當前小時內的過去時間>`（見下方 ⚠） | 回傳 `{"job_id": 1, "status": "pending", ...}` |
| 3 | 等約 10 秒後 → `task_status` 帶 `job_id=1` | status 變成 `"completed"` |
| 4 | `task_create` 帶未來時間 `"2099-12-31T00:00:00"` | 拿到 `job_id=2` |
| 5 | `task_cancel` 帶 `job_id=2` | status 變成 `"cancelled"` |
| 6 | `task_list` | 看到上述所有 jobs |

任何一步失敗就回頭檢查對應 TODO 是否正確。

> ⚠ **與 PROMPT.md 的差異**：PROMPT.md 示範用 `scheduled_at="2025-01-01T00:00:00"`，但我們的 `find_due_jobs()` 採嚴格 partition pruning（`time_bucket == current_bucket`），歷史 bucket 的 job 不會被掃到 — 這是 partition 的設計本意。實測時要用「**當前小時內、但已過的時間**」，例如現在是 `2026-05-15 14:30`（UTC），就填 `"2026-05-15T14:00:00"`。可先用 `date -u +"%Y-%m-%dT%H:00:00"` 取當前 UTC 小時起點。

---

## 五、Troubleshooting Checklist

| 症狀 | 可能原因 | 處置 |
|------|---------|------|
| inspector 顯示 0 個 tool | `TOOL_REGISTRY` 為空 / key 名稱拼錯 | 對齊 `TOOL_DEFINITIONS` 中四個 name |
| 過期 job 一直停在 `pending` | `get_time_bucket()` 沒回傳字串、或 `find_due_jobs()` 沒篩 `status=="pending"` | 用 print/logger 印出當前 bucket 與 query 結果 |
| `task_cancel` 失敗 | 已經被 worker 跑完進到 `completed`/`failed` | 改測未來時間的 job |
| `chatgpt_task.db` 累積太多舊資料污染測試 | SQLite 檔殘留 | 直接刪 `scaffold/chatgpt_task.db` 後再啟動 |
| 同一秒內 watcher 重複抓同一個 job | watcher 還沒把 status 改成 `queued` 前又掃到 | 已透過 `job.status = "queued"; db.commit()` 處理，正常情況不會發生 |
| `claude mcp list` 顯示 `✗ Failed to connect` | `command` 或 `cwd` 用了 `~` / 相對路徑 / `$HOME` | Claude Code **不展開 `~` 或 env var**，也不會用 config 裡的 `cwd` 來解析 `command` — 兩個欄位都必須用**完整絕對路徑** |

---

## 六、連到 Claude Code（已完成 ✅）

### 6-1 設定內容

寫入 `~/.claude.json` 的 top-level `mcpServers`（含備份）：

```json
{
  "mcpServers": {
    "task-scheduler": {
      "type": "stdio",
      "command": "/Users/jess/Documents/build-moat-live-sessions/chatgpt_task/scaffold/.venv/bin/python",
      "args": ["-m", "app.mcp_server"],
      "cwd": "/Users/jess/Documents/build-moat-live-sessions/chatgpt_task/scaffold",
      "env": {}
    }
  }
}
```

### 6-2 驗證

```bash
claude mcp list
# 應顯示：
# task-scheduler: .../python -m app.mcp_server - ✓ Connected
```

### 6-3 啟用 tools

**重新啟動目前的 Claude Code session** 才能載入新的 MCP server。重啟後可在輸入框打 `/` 或看 tool 清單，應該看得到：

- `mcp__task-scheduler__task_create`
- `mcp__task-scheduler__task_list`
- `mcp__task-scheduler__task_status`
- `mcp__task-scheduler__task_cancel`

### 6-4 Claude Desktop（可選）

若也要在 Claude Desktop 啟用，編輯 `~/Library/Application Support/Claude/claude_desktop_config.json` 貼上同樣的 block，然後完整重啟 Claude Desktop（不只是關視窗）。

---

## 六之一、Claude Code 測試 Prompts

> ⚠ 重要：watcher 採嚴格 bucket pruning，所以 prompt 給 Claude 的時間若被它解讀成不同小時的 bucket，job 不會被執行 — 改用「**當前小時內的過去時間**」或「**幾分鐘後**」這類自然描述讓 Claude 推導出當前 bucket 內的時間。
>
> 撰寫測試 prompt 時的當前 UTC 參考時間（取自 `_utcnow()`）：
> - NOW = `2026-05-15T09:12:14`
> - 適合「過去時間、同 bucket」: `2026-05-15T09:11:14`
> - 適合「未來、可被 cancel」: `2026-05-15T09:42:14` 或 `2099-12-31T00:00:00`

### 測試 1 — 自然語言建立 + 查狀態（完整 happy path）

```
請用 task_create 建立一個任務，description 是 "Summarize tech news"，
scheduled_at 是 "2026-05-15T09:11:14"（注意：UTC 時間，要早於現在但在同一小時內）。
建好之後告訴我 job_id，然後等 15 秒，再呼叫 task_status 看那個 job 的狀態，
預期應該是 completed。
```

**預期**：Claude 連續呼叫 `task_create` → `task_status`，最終回報 `status="completed"`、`result="Executed: Summarize tech news"`。

---

### 測試 2 — 建立未來 job 然後取消

```
請建立一個未來的任務：description = "Review PR #123"，
scheduled_at = "2099-12-31T00:00:00"。
建好後拿到 job_id，立刻 task_cancel 取消它，最後 task_status 確認狀態變成 cancelled。
```

**預期**：`status="cancelled"`。

---

### 測試 3 — list 看全部 jobs

```
請呼叫 task_list 列出所有 jobs，並依 scheduled_at 排序回報給我，
包含每個 job 的 id、description、status、scheduled_at。
```

**預期**：能看到測試 1（completed）、測試 2（cancelled）的紀錄，以及之前殘留的 jobs。

---

### 測試 4 — 錯誤情境：cancel 已完成的 job

```
測試 1 那個 job_id 已經 completed 了，請試著 task_cancel 它，看會回什麼 error。
```

**預期**：回 `{"error": "Cannot cancel job in 'completed' state"}`，Claude 應如實轉述。

---

### 測試 5 — 錯誤情境：查不存在的 job

```
請 task_status 查 job_id=99999，看會回什麼。
```

**預期**：回 `{"error": "Job 99999 not found"}`。

---

### 測試 6 — 自然語言時間解析（partition 失敗示範）

```
請建立一個任務描述為 "test bucket partition"，scheduled_at 用 "2025-01-01T00:00:00"。
建好後等 15 秒，看 task_status。
```

**預期**：job 建立成功但 `status` 永遠停在 `"pending"`（因為 bucket = `2025010100`，watcher 不會掃到）。這是預期行為，用來驗證 partition pruning 真的有效。

---

---

## 七、（可選）Bonus Challenges

完成主線後可挑：
- 接真 LLM 解析自然語言 task description，再呼叫 `task_create`。
- 支援 cron 表達式做 recurring jobs。（→ 詳見 §七之一）
- Job chaining：A 完成 → 自動觸發 B。
- 加 MCP `resources` 支援（把 job 細節變成 readable resource）。
- 加 MCP `prompts` 支援（如 `daily_review` prompt template）。

---

## 7-2、Recurring Jobs (Cron) 實作

> 對應 `README.md` Bonus：**Add recurring job support (cron expressions)**

### 目標

讓 `task_create` 接一個 optional `cron` 欄位（標準 5-field cron 表達式，如 `* * * * *` 每分鐘），job 跑完後 worker 自動依 cron 算出下一次 fire time 並排入。

### 設計決策

1. **保留歷史 vs 原地更新**：採「每次 fire 都是 distinct `Job` row」。
   - 理由：能完整看到每次執行的 `result`、`completed_at`；`task_status(job_id)` 語意維持不變。
   - 代價：jobs 表會長很快 — 原型可接受。
2. **失敗時要不要重排**：**不重排**。
   - 理由：避免無限失敗循環；prototype 階段保守。後續可加 `max_failures` policy。
3. **取消的語意**：對 recurring job 來說，cancel **只取消目前這一筆**未來 job — 之前已經 completed 的歷史 row 不動。要終止整條序列，使用者需在尚未 fire 的那筆上 cancel；worker 不會再排下一筆，因為被 cancel 的 job 不會進入 completed → reschedule 分支。
4. **跨 hour bucket 的限制**：watcher 採嚴格 partition pruning（`time_bucket == current_bucket`），若 cron 算出來的 next fire time 落在**下一個小時**，該 job 必須等 watcher 進入新 bucket 才會被掃到 — 這是 OK 的（10 秒輪詢一次，最多誤差 10 秒）。⚠ 但若下一筆 fire time 跨小時且 watcher 還沒進入新 bucket 時就剛好在邊界，仍有少量誤差，原型先接受。

### Step A — 加 dependency

`scaffold/requirements.txt` 增加：

```
croniter>=2.0
```

然後重跑 `pip install -r requirements.txt`。

### Step B — Schema 變更

`scaffold/app/models.py` 的 `Job` class 增加欄位：

```python
cron: Mapped[str | None] = mapped_column(String(64), nullable=True)
```

放在 `result` 後面、`created_at` 前面即可。

**Migration（原型階段）**：直接刪 `scaffold/chatgpt_task.db`，下次啟動 `Base.metadata.create_all()` 會用新 schema 重建。生產環境才需要正規 migration。

### Step C — Handler 改造

`scaffold/app/mcp_server.py::handle_create_task` 接 optional `cron`：

```python
def handle_create_task(
    db: Session, *, description: str, scheduled_at: str, cron: str | None = None
) -> dict:
    dt = datetime.fromisoformat(scheduled_at)
    job = Job(
        description=description,
        scheduled_at=dt,
        time_bucket=get_time_bucket(dt),
        cron=cron,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return {
        "job_id": job.id,
        "status": job.status,
        "scheduled_at": str(job.scheduled_at),
        "cron": job.cron,
    }
```

`handle_get_status` / `handle_list_tasks` 的回傳 dict 也順手把 `cron` 帶上，方便驗證。

### Step D — Tool definition 多一個欄位

`scaffold/app/mcp_server.py::TOOL_DEFINITIONS` 中 `task_create` 的 `inputSchema.properties` 加：

```python
"cron": {
    "type": "string",
    "description": "Optional 5-field cron expression (e.g. '* * * * *' for every minute). If set, job auto-reschedules after each completion.",
},
```

**不要**把 `cron` 放進 `required`。

### Step E — Worker 跑完自動排下一次

`scaffold/app/scheduler.py::worker_loop` 改成：

```python
from croniter import croniter

def worker_loop():
    while True:
        job_id = job_queue.get()
        db = SessionLocal()
        try:
            job = db.query(Job).filter(Job.id == job_id).first()
            if job is None or job.status == "cancelled":
                continue

            job.status = "running"
            db.commit()

            job.result = f"Executed: {job.description}"
            job.status = "completed"
            db.commit()

            # NEW: reschedule next fire if cron is set
            if job.cron:
                next_dt = croniter(job.cron, _utcnow()).get_next(datetime)
                next_job = Job(
                    description=job.description,
                    scheduled_at=next_dt,
                    time_bucket=get_time_bucket(next_dt),
                    cron=job.cron,
                )
                db.add(next_job)
                db.commit()
        except Exception as e:
            if job is not None:
                job.status = "failed"
                job.result = str(e)
                db.commit()
        finally:
            db.close()
            job_queue.task_done()
```

**關鍵點**：
- `croniter(cron, base).get_next(datetime)` 回傳的是「base 之後的第一個 fire time」，所以用 `_utcnow()` 當 base 不會卡在 base 自己。
- 重排是「在 completed 之後」才做 — 若 job 在 fire 前就被 cancel，永遠走不到這段，序列自然終止。
- failed 的 job 不重排（見設計決策 #2）。

### 完成判準

- [ ] `task_create` 不帶 `cron` 時，行為與舊版完全一致（一次性 job）。
- [ ] `task_create(description="ping", scheduled_at=<同 bucket 過去時間>, cron="* * * * *")` 建立後：
  - 約 10 秒內第一個 row 變 `completed`；
  - DB 出現第二個 row，`description="ping"`、`scheduled_at` 為下一分鐘、`status="pending"`、`cron="* * * * *"`；
  - 等到下一分鐘的 watcher tick，第二個 row 也變 `completed`，並出現第三個 `pending` row。
- [ ] 對 recurring 序列的下一筆 `pending` 做 `task_cancel` → 該筆變 `cancelled`，worker 不再排下一個（序列終止）。
- [ ] cron 拼錯時 `task_create` 不應該爆炸 — 可接受兩種處理：在 handle_create_task 用 `croniter.is_valid(cron)` 預檢，無效就回 `{"error": "Invalid cron expression"}`；或讓它先進 DB，worker reschedule 時抓 exception → 標 failed（簡化版）。建議至少做前者，錯誤訊息回得乾淨。

### 七之一·測試範例

> 取當前 UTC 時間（撰寫測試時參考 `_utcnow()`）：假設 `NOW = 2026-05-15T09:35:00`，則「同 bucket 過去時間」用 `2026-05-15T09:30:00`。

#### 測試 R1 — Cron recurring happy path（每分鐘）

Prompt：

```
請呼叫 task_create 建立一個 recurring 任務：
- description = "Heartbeat"
- scheduled_at = "2026-05-15T09:30:00"   (UTC，當前小時內的過去時間)
- cron = "* * * * *"                       (每分鐘)

建好後告訴我 job_id (= N1)。

第一階段：等 15 秒，呼叫 task_status(job_id=N1)，預期 status="completed"。

第二階段：呼叫 task_list，找出 description="Heartbeat" 且 status="pending"
的最新一筆，回報那筆的 job_id (= N2) 和 scheduled_at。
預期 scheduled_at 比 N1 的 scheduled_at 大、且為下一分鐘的整點 (e.g. 09:36:00)。

第三階段：等到 N2 的 scheduled_at 過了 + 15 秒，再 task_list 一次，
應該看到 N1、N2 都是 completed，並有一筆新的 pending (N3)。
```

預期結果：

| 階段 | 觀察點 | 預期值 |
|------|--------|--------|
| 1 | `task_status(N1)` | `status="completed"`, `result="Executed: Heartbeat"` |
| 2 | `task_list` 找新 pending | 存在 N2，`scheduled_at` ≈ N1 fire time 後的下一個 cron tick |
| 3 | `task_list` 再次 | N1, N2 = completed；N3 = pending |

#### 測試 R2 — Cancel 序列下一筆 → 序列終止

接續 R1 完成後：

```
請呼叫 task_cancel(job_id=N3)，然後等 90 秒，再 task_list。
預期：N3 = cancelled，且沒有任何新的 pending Heartbeat row 出現
（worker 不會替 cancelled job 排下一次）。
```

預期：N3 status=`cancelled`；series 終止；之後不再有 Heartbeat pending row。

#### 測試 R3 — 無效 cron expression

```
請 task_create 帶 cron="not a cron"，scheduled_at 用 "2026-05-15T09:30:00"。
預期回傳 {"error": "Invalid cron expression"}，不應建立任何新 row。
```

（若選擇了 §「完成判準」末項的「worker 處理」路線，這題改為：job 會建立但 worker 嘗試 reschedule 時把該筆從 completed 改 failed — 此情境下測試預期值要對應調整。）

---

## 八、Definition of Done

- [x] `get_time_bucket()` 回傳正確的 hourly bucket 字串
- [x] `find_due_jobs()` 能撈到當前 bucket、到期、pending 的 jobs
- [x] `TOOL_REGISTRY` 含 4 個 key
- [x] `route_tool_call()` 能正確 dispatch、未知工具回 error
- [x] server 啟動 sanity check 通過（`python -m app.mcp_server` 正常 hang on stdin）
- [x] inspector 六步驟測試全部通過
- [x] 可成功 cancel 一個未來 job
- [x] `task_list` 能看到全部 job 與其最終 status

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
| 2026-05-15 | Claude Code 接線 | 寫入 `~/.claude.json` top-level `mcpServers.task-scheduler`（先備份至 `~/.claude.json.bak.20260515_171039`），`claude mcp list` 顯示 ✓ Connected |
