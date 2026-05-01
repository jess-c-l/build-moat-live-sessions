# QR Code Generator Prototype

## System Requirements

Build a dynamic QR code system where:
- Users submit a long URL and get back a short URL token + QR code image
- The QR code encodes a short URL that redirects (302) to the original URL via your server
- Users can modify the target URL after QR code creation
- Users can delete a QR code (soft delete)
- Users can optionally set an expiration timestamp on create or update
- Deleted or expired links return appropriate HTTP status codes
- URL validation: format check, normalization, malicious URL blocking

## Design Questions

Answer these before you start coding:

1. **Static vs Dynamic QR Code:** Why does this system use dynamic QR codes (encode short URL) instead of static (encode original URL directly)? When would you choose static instead?

   QR code 一旦印出來就改不了了——傳單、名片、貼紙、產品包裝。如果直接把原始 URL
   編進去(static),那網址要改、要下架、要換活動連結,整批印刷品就作廢。
   
   Dynamic 的作法是 QR code 永遠指向 yourservice.com/r/abc123,後端 mapping
   隨時能改。額外好處:
   
   - 可分析:每次 scan 都經過你的 server,可以記 scan 次數、來源、時間
   - 可撤銷:soft delete 後回 410,連結立刻失效
   - 可過期:設 expiration 後自動失效
   - 短網址更小:QR code dot 數變少,容錯率高、列印小一點也掃得到
   
   什麼時候用 Static?
   
   - 不需要追蹤、不需要改變的場景:Wi-Fi 密碼、聯絡資訊 vCard、純文字
   - 不想依賴外部服務(static QR 不會因為你 server 掛掉而失效)
   - 隱私敏感:不想讓中間 server 知道誰掃了
   - 離線場景:掃完直接拿到資料,不需要連線到你的 server

2. **Token Generation:** How will you generate short URL tokens? What happens when two different URLs produce the same token? How does collision probability change as the number of tokens grows?
   作法選擇:
   兩種主流路線:
 
    1. Random(推薦):用 secrets.token_urlsafe(6) 產生 8 字元 base64-url(約 48 bits
       熵)。產完查 DB 是否撞到,撞到就 retry。
    2. Hash-based:hash(url + salt)[:8]。問題:同一個 URL 永遠產同一個
       token,變成沒辦法兩個使用者各自做自己的短網址。
 
   我選 Random,因為這個系統 URL 可以更新,token 不該跟 URL 綁定。
   
   兩個不同 URL 撞到同一個 token 怎麼辦?
   
   INSERT 時用 DB 的 unique constraint,撞到就 retry 一次產新 token。重試 3 次都撞才回
   500(實務上不可能發生)。
   
   碰撞機率怎麼隨規模變化?
   
   這是 birthday problem。token space 是 64^N(N = token 長度)。已經有 k 個 token
   時,下一次產生撞到的機率約 k / 64^N。
   
   - 8 字元 → 64^8 ≈ 2.8 × 10^14。存到 1 億筆,單次碰撞率約 1/2,800,000,可以忽略
   - 6 字元 → 64^6 ≈ 6.8 × 10^10。存到 100 萬筆,碰撞率開始變顯著(~1.5%),需要更積極的
     retry
   - 規模再大就要加長 token 或上 base62 + 更長字元
   
   選 token 長度其實是在「QR code 美觀(短)」vs「碰撞機率(長)」做 trade-off。

3. **Redirect Strategy:** Why 302 (temporary) instead of 301 (permanent)? What are the trade-offs for analytics, URL modification, and latency?
   301(Permanent)會被瀏覽器永久 cache——下次再 visit /r/abc123,瀏覽器直接跳到 cached
   的目標 URL,根本不會碰你的 server。
   302(Temporary)告訴瀏覽器「這次去這裡,下次再問我一次」,每次 scan 都會經過 server。

   Trade-offs:
   
   ┌─────────────┬─────────────────────────────────┬─────────────────┐
   │    面向     │               301               │       302       │
   ├─────────────┼─────────────────────────────────┼─────────────────┤
   │ Latency     │ 第二次起 0 round trip           │ 每次都打 server │
   ├─────────────┼─────────────────────────────────┼─────────────────┤
   │ Analytics   │ 只記得到第一次                  │ 每次都記得到    │
   ├─────────────┼─────────────────────────────────┼─────────────────┤
   │ 可改 target │ ❌(已 cache 的客戶端拿不到新值) │ ✅              │
   ├─────────────┼─────────────────────────────────┼─────────────────┤
   │ 可撤銷      │ ❌                              │ ✅              │
   ├─────────────┼─────────────────────────────────┼─────────────────┤
   │ SEO         │ 把 link juice 傳到 target       │ 不傳            │
   └─────────────┴─────────────────────────────────┴─────────────────┘
   
   對 dynamic QR 系統,302 是唯一合理選擇。301 只適合永久搬家、不需要
   analytics、不需要可變更的場景。
   
   (進階:也可以回 302 + Cache-Control: no-store 強化,確保 proxy 也不 cache。)


4. **URL Normalization:** What normalization rules do you need? Why is `http://Example.com/` and `https://example.com` potentially the same URL?
   1. 
   - 統一用https
   - 如果有port 加上去
   - 如果是blocked domain就噴Error

   2. 一樣
      URL 的某些部分大小寫不敏感或有等價形式:
      - Scheme 不分大小寫(HTTP:// = http://)
      - Host 不分大小寫(Example.COM = example.com),因為 DNS 不分大小寫
      - Trailing slash on root path:example.com 和 example.com/ 在 HTTP 語意上等價
      - Default port:http://example.com:80 = http://example.com
      - http vs https:雖然技術上不同 protocol,但對大部分網站是同一個資源
      Path 和 query 是大小寫敏感的(/About ≠ /about),要小心不要過度 normalize。

5. **Error Semantics:** What should happen when someone scans a deleted link vs a non-existent link? Should the HTTP status codes be different?

   Deleted vs Non-existent 的差別:
   
   兩者語意不同,HTTP 也有不同的 status code 對應:
   
   ┌───────────────────────┬──────────────────┬───────────────────────────────────┐
   │         情境          │      Status      │               語意                │
   ├───────────────────────┼──────────────────┼───────────────────────────────────┤
   │ Token 從來沒存在過    │ 404 Not Found    │ 「這個資源不存在」                │
   ├───────────────────────┼──────────────────┼───────────────────────────────────┤
   │ Token 曾經存在,被刪除 │ 410 Gone         │ 「這個資源存在過,但已被永久移除」 │
   ├───────────────────────┼──────────────────┼───────────────────────────────────┤
   │ Token 曾經存在,但過期 │ 410 Gone(或 404) │ 同上,過期等同刪除                 │
   └───────────────────────┴──────────────────┴───────────────────────────────────┘
   
   為什麼要區分?
   
   1. 語意正確:HTTP 規範就是這樣設計的。410 明確告訴
      client/crawler「不要再來了,這個東西不會回來」,搜尋引擎看到 410 會更積極 deindex
   2. Debug 更容易:user 回報「我的連結壞了」,看到 410 就知道是被刪/過期,看到 404
   就知道是 token 打錯
   3. 快取行為不同:某些 proxy 對 410 比 404 更積極快取
   
   實務建議:
   
   - Soft delete:DB 留著紀錄(deleted_at、expires_at),query 時判斷狀態
   - 過期可以選擇回 410 或新增 Gone-Reason: expired 自訂 header
   - 不要回 200 + 「此連結已失效」HTML 頁面當作 redirect endpoint 的回應——QR code
   scanner / 自動化工具會誤判
   - 但是可以設計一個 fallback:redirect endpoint 回 302 到一個 /expired
   頁面,讓使用者看到友善訊息,同時讓 API endpoint(/api/qr/{token})回正確的
   410。這是兩個不同的 endpoint,不衝突
   
   邊界情境:
   - Token 格式根本就不對(例如長度不對、含非法字元):可以早早回 400 Bad Request,不用查
     DB
   - 同一個 token 曾被刪除然後 token recycle:不要 recycle deleted token,讓 410 永遠是
     410

## Verification

Your prototype should pass all of these:

```bash
# Create a QR code
curl -X POST http://localhost:8000/api/qr/create \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}'
# → 200, returns {"token": "...", "short_url": "...", "qr_code_url": "...", "original_url": "..."}

# Redirect
curl -o /dev/null -w "%{http_code}" http://localhost:8000/r/{token}
# → 302

# Get info
curl http://localhost:8000/api/qr/{token}
# → 200, returns token metadata

# Update target URL
curl -X PATCH http://localhost:8000/api/qr/{token} \
  -H "Content-Type: application/json" \
  -d '{"url": "https://new-url.com"}'
# → 200

# Redirect now goes to new URL
curl -o /dev/null -w "%{redirect_url}" http://localhost:8000/r/{token}
# → https://new-url.com

# Delete
curl -X DELETE http://localhost:8000/api/qr/{token}
# → 200

# Redirect after delete
curl -o /dev/null -w "%{http_code}" http://localhost:8000/r/{token}
# → 410

# Non-existent token
curl -o /dev/null -w "%{http_code}" http://localhost:8000/r/INVALID
# → 404

# QR code image
# (create a new one first, then)
curl -o /dev/null -w "%{http_code} %{content_type}" http://localhost:8000/api/qr/{token}/image
# → 200 image/png

# Analytics
curl http://localhost:8000/api/qr/{token}/analytics
# → 200, returns {"token": "...", "total_scans": N, "scans_by_day": [...]}
```

## Suggested Tech Stack

Python + FastAPI recommended, but you may use any language/framework.
