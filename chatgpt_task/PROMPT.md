# ChatGPT Task Scheduler Prototype

## System Requirements

Build a job scheduler with an MCP (Model Context Protocol) interface:
- Users schedule tasks for future execution via MCP tool calls
- A background watcher scans for due jobs and pushes them to a queue
- Workers pull jobs from the queue and execute them
- Support task creation, listing, status checking, and cancellation
- Tool naming follows namespace + action verb pattern (e.g., `task_create`; see Design Question 4 for why `_` not `.`)

### Architecture

```
User → MCP Tool Call → Job Scheduler API → DB
                                            ↓
                              Watcher (scans DB) → Queue → Worker (executes)
```

## Design Questions

Answer these before you start coding:

1. **Watcher vs Cron:** Why separate the watcher from the worker? What problems does a single cron job that both scans and executes have?
---
We separate the watcher from the worker mainly for separation of concerns and scalability.
  - The watcher focuses on scanning and scheduling jobs.
  - The worker focuses on executing jobs.
    
  - This allows each layer to scale independently and prevents execution logic from affecting scheduling reliability. 
    - Example:
      A watcher may scan the database every minute. 
      Workers handle actual email sending. 
        
    - Under normal traffic, 1 worker may be enough. 
    - During a large campaign, workers can scale horizontally to handle the increased workload, while the watcher remains unchanged because scanning itself is lightweight.
      
---

If a single cron job both scans and executes, several problems can happen:
  - Long-running jobs may delay future scans.
  - A crash during execution may stop scheduling.
  - It becomes harder to scale execution independently.
  - Multiple cron instances may accidentally execute the same task twice.
    
  - Also, workers become more reusable because they can be triggered not only by watchers, but also by APIs, events, retries, or manual operations.
   
---


2. **Queue Layer:** Why put a queue between the watcher and worker instead of having the watcher call the worker directly? What are the benefits?

---

Queue acts as a buffer that decouples production and consumption, absorbs traffic spikes, and improves scalability and reliability by enabling asynchronous and fault-tolerant processing.

---

1. Decoupling（解耦）
   watcher 不需要等 worker 執行完成，只負責丟 job。

2. Load buffering（削峰填谷）
   queue 吸收 spike，避免 worker 被瞬間流量壓垮。

3. Scalability（水平擴展）
   watcher 可以 scale
   worker 可以 scale
   彼此互不影響

4. Reliability（可靠性） 
   worker fail 時： job 還在 queue, 可以 retry / redelivery

5. Async processing（非同步）
   watcher enqueue 後立即返回，不阻塞執行.


3. **Time Bucket Partitioning:** Instead of `SELECT * WHERE scheduled_at <= now()`, why partition jobs by time bucket (e.g., hour)? What happens to query performance at 1M+ jobs without partitioning?
---
   - Without partitioning, the query scans historical data and grows with total dataset size; with time partitioning, it only scans the relevant partition, reducing IO and improving cache locality.
---
在 1M+ jobs 情境下的差異
  - ❌ 沒 partition：
      - 每次 query 都在大量歷史 job 中做 range scan
      - 隨著資料成長，query latency 逐漸變慢
      - DB 負載持續上升（即使只有少數 ready jobs）
  - ✅ 有 time bucket partition：
      - query scope 被限制在「current + next bucket」
      - historical data 不會影響 hot path
      - 可搭配 partition pruning，大幅降低 IO
---

4. **Tool Naming:** Why `task_create` instead of `createTask`? How does naming convention affect LLM tool selection accuracy?

> ⚠ 原本想用 `task.create`（object-first + dot 分隔），但 Anthropic API 的 tool name 必須匹配 `^[a-zA-Z0-9_-]{1,128}$`，不允許 `.`。Claude Code 載入 MCP server 時會靜默過濾掉含 `.` 的 tool（`claude mcp list` 仍顯示 ✓ Connected，但 session 看不到工具）。因此實際使用 `_` 作為 namespace 分隔。MCP inspector 比較寬鬆所以本機看得到，這也是「inspector 過、Claude Code 沒過」的常見坑。

---

- Object-first naming aligns tools with resource namespaces, improving LLM intent mapping and reducing ambiguity in tool selection.

---

- LLM 在 tool selection 本質是「classification problem」
- namespace = implicit label grouping
- action suffix = subcategory

- 降低 token ambiguity（`task_create` 的結構比 `createTask` 更清晰、可解析）
- 減少 tool space confusion（不同 domain 的 tool 更容易被區分）
- 提升 prompt intent 的對齊（user intent → resource → action）


5. **Registry vs If-Else:** Why use a dictionary registry to route tool calls instead of if-else chains? What happens when you need to add the 20th tool?
   - 用 registry 取代 if-else，因為它把 routing 從「逐條判斷」變成「key-based lookup」，讓查找變 O(1)，也更容易擴展。
   - 主要差異有三點： 
     - 可擴展性：新增 tool 不需要改 core logic
     - 可維護性：避免 if-else 變成 decision tree
     - 可讀性：routing 變成 declarative mapping

## Verification

Your prototype is a real MCP server. Test it with the MCP inspector — no Claude needed.

### 1. Start the server (sanity check)

```bash
python -m app.mcp_server
```

The process should hang waiting on stdin (it's a stdio MCP server — that's correct). Ctrl+C to stop. If you see an `ImportError` or other crash, fix that first.

### 2. Run the MCP inspector

Requires Node.js (uses `npx`).

```bash
npx @modelcontextprotocol/inspector python -m app.mcp_server
```

This opens a browser GUI (usually `http://localhost:5173`).

Steps in the GUI:

1. Click **Connect** -> should show 4 tools: `task_create`, `task_list`, `task_status`, `task_cancel`
2. **task_create** -> fill `description="Summarize tech news"`, `scheduled_at="2025-01-01T00:00:00"` (past time so watcher picks it up immediately) -> **Run Tool** -> response should include `{"job_id": 1, "status": "pending", ...}`
3. Wait ~10 seconds, then **task_status** -> `job_id: 1` -> status should now be `"completed"`
4. **task_create** with future time `"2099-12-31T00:00:00"` -> get `job_id: 2`
5. **task_cancel** -> `job_id: 2` -> status `"cancelled"`
6. **task_list** -> see all your jobs

### 3. (Optional) Connect to Claude Desktop / Claude Code

Once the inspector tests pass, the server is ready. To talk to it through Claude:

**Claude Desktop**: edit `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) and add (use absolute paths):

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

Restart Claude Desktop fully. The 🔨 icon in the chat input should show 4 tools.

**Claude Code**: edit `~/.claude.json` (top-level `mcpServers` for user scope) with the same block, or run `claude mcp add` from inside `scaffold/`.

Then chat:
> "Schedule a task to review PR #123 tomorrow at 9am."
> -> Claude calls `task_create` -> returns job_id
> "What's the status of that task?"
> -> Claude calls `task_status`

## Suggested Tech Stack

Python + the official `mcp` SDK is recommended (already in `requirements.txt` for the Guided Track). Challenge Track may use any language with an MCP SDK.
