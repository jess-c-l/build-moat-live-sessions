## Which retrieval strategy did you choose, and why?
  1. Markdown KB
  2. 
      - knowledge base是結構化資料，用Markdown進行keyword search的可實作出來。
      - 相對於Vector RAG，Markdown KB不需要embedding pipeline 和 vector database，方便實作，且容易維護。
      - 關鍵理由：**Vector RAG 會把「檢索」也變成一個外部 API 依賴（embedding）**。
        - `/index` 時每個 chunk 都要打 embedding API 才能建向量庫（文件越多越慢、越花錢，實測 OpenAI 還撞 `429 insufficient_quota`）。
        - `/chat` 時連 query 都要先 embed 才能搜尋，等於每一次查詢都多綁一次外部 API 往返。
        - index / query / 生成三步都吃 API key，任一步額度爆掉或服務掛掉整條檢索就停擺；而 Markdown KB 的 BM25 是純本地，只有最後生成答案才需要 API。
      - 延遲觀察：實測兩者端到端時間「差不多」，因為延遲幾乎都被 LLM 生成那一步吃掉，BM25 vs FAISS 的檢索差異（毫秒級）感覺不出來。換句話說 Vector RAG 在這個規模並沒有更快（甚至因為多一次 query embedding 略慢），所以速度不是選它的理由——這反而是支持選簡單的 Markdown KB 的證據。
      - 整體流程: 
```
        Markdown files
        ↓
        keyword search (grep / BM25)
        ↓
        top matching sections
        ↓
        build prompt
        ↓
        LLM answer
```

## What is the retrieval unit in your design: file, section, or chunk?
  1. section（以 heading 切分的段落，id 格式為 filename#heading）
  2. 流程是：每個 Markdown file 先用 HEADING_RE 依 # 標題拆成多個 section，每個 section 的 tokens（含 heading + content）才是 BM25 打分的對象。BM25 對所有 section 逐一計分、排序，取 top-k section 當作 context，引用時用
     filename#heading 指回原文。
  3. 為什麼選 section 而不是 file 或 chunk：
    - 不用 file：一個檔混了多個主題（如 refund_policy 同時有 timeline、cancellation、non-refundable），整檔丟 BM25 會稀釋分數、context 雜訊大，引用也只能指到檔名、不夠精確。
    - 不用 chunk（固定字數切）：Markdown 的 heading 本身就是天然的語意邊界，且本知識庫每個 section 都很短（最長約 200 字），再切成定長 chunk 只會破壞語意完整性、徒增複雜度。
    - 選 section：粒度剛好——語意完整、長度適中、且 filename#heading 天生就是可驗證的引用 ID。


## How do you decide what goes into the prompt?
  1. 根據BM25的search結果，將top matching sections的內容放入prompt中，並且在prompt中加入使用者的query，讓LLM能夠根據這些資訊來生成答案。

## How do you cite sources so users can inspect the original Markdown?
  1. 每個 section 在建索引時就被賦予 filename#heading 格式的引用 ID（如 refund_policy.md#refund-timeline），由 slugify(heading) 產生。
  2. 組 prompt 時，每段 context 前都標上 [Source: <id>]；SYSTEM_PROMPT 強制 LLM 只能引用 CONTEXT 中字面出現過的 ID，禁止杜撰或竄改，藉此把引用綁死在實際檢索到的來源上。
  3. API 回應除了答案內嵌的 [Source: filename#heading]，還另附 sources 陣列（含 source、heading、score、content 預覽）。
  4. 因為引用 ID 直接對應 docs/<filename> 裡的 # heading，使用者可循 ID 翻回原始 Markdown 的那一段，驗證答案是否如實。

## What should happen when retrieval finds weak or irrelevant results?
  1. 目前實作：兩道關卡。
      - (a) 檢索層 search 只保留 BM25 score > 0 的 section，若完全無匹配則回空、query 直接回固定句 I cannot confirm from the knowledge base.，不浪費一次 LLM 呼叫。
      - (b) 若撈到弱相關 section，SYSTEM_PROMPT 要求 LLM 在 CONTEXT 不足時同樣回那句、且不得引用，避免硬湊答案產生幻覺。
  2. sources 與 answer 解耦：sources 是在呼叫 LLM 之前就由檢索結果組好的，所以即使答案是「找不到」，sources 仍可能列出有分數的 section——它代表「bot 檢索時看了哪些段落」，方便判斷是知識庫真的沒有、還是檢索抓錯段。
  3. 設計取捨：寧可誠實說「找不到」，也不要用低品質 context 強行作答。

## When would you switch from Markdown KB to Vector RAG?
  - 當 knowledge base 開始出現以下情況時，我會從 Markdown index 切換到 Vector RAG：
    - 文件數量大量增加
    - keyword search precision 降低
    - 同義詞變多
    - 文件之間語意關聯變複雜
    - 使用者問題變成自然語言問答，而不是精確查找
    
    例如： 10~100 個文件時，Markdown index + grep 可能就夠。

    但到：
    - 幾千份文件
    - 大量非結構化內容
    - 多團隊知識文件
    
    Vector retrieval 的 semantic search 效果會更好。

## When would you switch from Vector RAG back to a Markdown index?
  - 如果 knowledge base：
    - 規模不大 
    - 結構明確 
    - 文件品質高 
    - 查詢模式deterministic

    我會偏向 Markdown index。

    因為： 
    - simpler architecture
    - 不需要 embedding pipeline
    - 不需要 vector database
    - easier debugging
    - retrieval 可解釋性更高

    例如： 
    - API docs、規格文件。

## If the knowledge base grows from 10 files to 100,000 files, what changes?
- **Retrieval Strategy**: Markdown index 切換到 Vector RAG，因為
  - keyword search 準確率下降
  - 語意相似度提高
  - file retrieval noise 太大

- **Indexing**: 需要實現更高效的索引方法，例如使用分布式索引或增量索引來處理大量文件。
- **Storage**: 需要考慮存儲解決方案，例如使用雲存儲或分布式文件系統來存儲大量的 Markdown 文件和索引數據。
- **Performance**: 需要優化檢索性能，例如使用更高效的搜索算法、緩存熱門查詢結果等。
- **Maintenance**: 
  - 大量文件很容易出weak context、duplicate chunk、stale document、retrieval noise 等問題
  - 需要automated reindexing pipeline、定期清理過時文件、監控檢索質量等措施來維護知識庫。