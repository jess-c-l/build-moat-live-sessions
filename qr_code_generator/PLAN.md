# QR Code Generator — 執行計畫

> 重點:**先把實作完成、curl 全綠**,Design Questions 留到最後再寫。

---

## Phase 0:環境準備

```bash
cd /Users/jess/Documents/build-moat-live-sessions/qr_code_generator/scaffold
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

- [ ] venv 建立完成
- [ ] 套件安裝完成

---

## Phase 1:實作三個 TODO(核心)

### Step 1 — `app/url_validator.py` 的 `validate_url()`

**任務:** 驗證 + normalize URL,失敗 raise `ValueError`。

**檢查:**
- [ ] 長度 ≤ `MAX_URL_LENGTH` (2048)
- [ ] `urlparse(url).scheme` 是 `http` 或 `https`
- [ ] `is_blocked_domain(hostname)` 為 False

**Normalize:**
- [ ] hostname 轉小寫
- [ ] `http` → `https`
- [ ] 去掉 trailing `/`(但根路徑 `https://example.com/` → `https://example.com`)
- [ ] return normalized url string

---

### Step 2 — `app/token_gen.py` 的 `generate_token()`

**任務:** 產生 7 字元 Base62 token,碰撞時重試。

**流程:**
- [ ] for `attempt in range(MAX_RETRIES)`:
  - [ ] 用 `time.time_ns()` 或 `attempt` 當 nonce
  - [ ] `digest = hashlib.sha256((url + str(nonce)).encode()).digest()`
  - [ ] `token = base62_encode(digest)[:TOKEN_LENGTH]`
  - [ ] 如果 `not token_exists_in_db(db, token)` → return token
- [ ] 全部失敗 → `raise RuntimeError("Failed to generate unique token")`

---

### Step 3 — `app/routes.py` 的 `redirect()`

**任務:** Cache → DB → 404/410 的 redirect 邏輯(熱路徑)。

**流程:**
- [ ] **Cache 命中:**
  - [ ] `if token in redirect_cache:` → `_record_scan(token, request, db)` → `return RedirectResponse(redirect_cache[token], status_code=302)`
- [ ] **Cache miss → 查 DB:**
  - [ ] `mapping = db.query(UrlMapping).filter(UrlMapping.token == token).first()`
  - [ ] `if mapping is None:` → `raise HTTPException(404)`
  - [ ] `if mapping.is_deleted:` → `raise HTTPException(410)`
  - [ ] `if mapping.expires_at and mapping.expires_at < datetime.utcnow():` → `raise HTTPException(410)`
  - [ ] 正常:`redirect_cache[token] = mapping.original_url` → `_record_scan(...)` → `return RedirectResponse(mapping.original_url, status_code=302)`

---

## Phase 2:啟動 + curl 驗證

```bash
uvicorn app.main:app --reload
```

逐條跑 PROMPT.md 底部的 curl,把 token 換進去:

| # | 測試 | 期望 |
|---|------|------|
| 1 | POST `/api/qr/create` | 200 + `{token, short_url, qr_code_url, original_url}` |
| 2 | GET `/r/{token}` | 302 |
| 3 | GET `/api/qr/{token}` | 200 + metadata |
| 4 | PATCH `/api/qr/{token}` 改 url | 200 |
| 5 | GET `/r/{token}` 看是否導到新 url | redirect_url = 新 url |
| 6 | DELETE `/api/qr/{token}` | 200 |
| 7 | GET `/r/{token}` 已刪除 | 410 |
| 8 | GET `/r/INVALID` | 404 |
| 9 | GET `/api/qr/{token}/image` | 200 + `image/png` |
| 10 | GET `/api/qr/{token}/analytics` | 200 + scan 統計 |

- [ ] 全部 10 個 curl 通過
- 
  ⏺ ---
  Phase 2 驗證 — 一步步執行

  Step A:啟動 server(Terminal A)

  cd /Users/jess/Documents/build-moat-live-sessions/qr_code_generator/scaffold
  rm -f qr_code.db
  source .venv/bin/activate
  uvicorn app.main:app --reload --port 8000

  ⏺ 這是 SQLAlchemy 2.0.36 跟 Python 3.14 不相容 的問題 — Mapped[bool] 用到的 Union
  型別在 Python 3.14 裡行為改了,舊版 SQLAlchemy 還沒適配。
  
  修法:升級 SQLAlchemy
  pip install 'sqlalchemy==2.0.43'


---

## Phase 3:回答 Design Questions(寫在 PROMPT.md)

寫到 PROMPT.md 第 15 行附近的「Design Questions」區塊下方。

- [ ] Q1:Static vs Dynamic QR
- [ ] Q2:Token generation + 碰撞
- [ ] Q3:302 vs 301
- [ ] Q4:URL normalization
- [ ] Q5:404 vs 410 語意

---

## Phase 4(選做):Bonus

- [ ] 簡單前端(HTML form 輸入 URL → 顯示 QR 圖)
- [V] **Add rate limiting to the create endpoint**(細節見下方 Step R)
- [V] 過期自動回 410(Phase 1 Step 3 已涵蓋;cache 改存 `(url, expires_at)`,redirect cache hit 時 inline 檢查過期,過期就 pop + fall through to DB → 410)
- [V] Admin cache invalidation:`POST /admin/cache/invalidate/{token}` 與 `POST /admin/cache/clear`,搭配手動改 DB 的偵錯場景

---

### Step R — `/api/qr/create` Rate Limiting

**任務:** 防止濫用建立短網址,同 IP 短時間內超過上限即回 429。

**選型:** `slowapi`(FastAPI 生態最常見,基於 `limits` 函式庫,語法接近 Flask-Limiter)。

**策略:**
- key:`get_remote_address`(以 client IP 當 key)
- 上限:`10/minute` 套在 `/api/qr/create`(可調)
- 超過 → 自動回 `429 Too Many Requests`,訊息走 slowapi 預設 handler

**實作步驟:**

1. **加入套件**
   - [ ] `scaffold/requirements.txt` 加 `slowapi==0.1.9`
   - [ ] `pip install -r requirements.txt`

2. **建立 Limiter(`app/main.py`)**
   - [ ] `from slowapi import Limiter, _rate_limit_exceeded_handler`
   - [ ] `from slowapi.util import get_remote_address`
   - [ ] `from slowapi.errors import RateLimitExceeded`
   - [ ] `limiter = Limiter(key_func=get_remote_address)`
   - [ ] `app.state.limiter = limiter`
   - [ ] `app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)`

3. **掛上 endpoint(`app/routes.py`)**
   - [ ] `from slowapi import Limiter` + `from slowapi.util import get_remote_address`
   - [ ] 引入共用 limiter(避免多個 instance):從 `app.main` import,或在 `routes.py` 建獨立 module-level limiter,於 `main.py` 用同一個
     - 推薦寫法:在 `app/limiter.py` 集中建立 `limiter = Limiter(key_func=get_remote_address)`,`main.py` 與 `routes.py` 都從這裡 import
   - [ ] `create_qr` 函式簽名加 `request: Request`(slowapi 需要)
   - [ ] 在 `create_qr` 上方加 `@limiter.limit("10/minute")`

4. **curl 驗證**
   - [ ] 同 IP 連發 11 次 `POST /api/qr/create`,第 11 次預期 `429`
   ```bash
   for i in $(seq 1 11); do
     curl -s -o /dev/null -w "%{http_code}\n" \
       -X POST http://localhost:8000/api/qr/create \
       -H 'Content-Type: application/json' \
       -d '{"url":"https://example.com/'$i'"}'
   done
   ```
   - [ ] 預期輸出:前 10 個 `200`,第 11 個 `429`

**注意事項:**
- `slowapi` 依賴 `request: Request` 參數能被 FastAPI 注入,**不要漏掉這個參數**,否則 limiter 會找不到 request 物件而 raise。
- 目前是 in-memory 計數,server 重啟即歸零;production 要改成 Redis backend(`Limiter(storage_uri="redis://...")`)。
- 若之後加上前端 / proxy(如 Nginx),需改用 `X-Forwarded-For`,可換成自寫 `key_func`。

---

## 進度追蹤

- [V] Phase 0:環境
- [V] Phase 1 Step 1:`validate_url`
- [V] Phase 1 Step 2:`generate_token`
- [V] Phase 1 Step 3:`redirect`
- [V] Phase 2:curl 全綠
- [V] Phase 3:Design Questions
- [ ] Phase 4:Bonus(選做)
