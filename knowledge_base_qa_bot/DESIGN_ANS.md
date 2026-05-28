## Which retrieval strategy did you choose, and why?
  1. Markdown KB
  2. 
      - knowledge base是結構化資料，用Markdown進行keyword search的可實作出來。
      - 相對於Vector RAG，Markdown KB不需要embedding pipeline 和 vector database，方便實作，且容易維護。
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
  1. file
  2. 根據目前的knowledge base, 我將file傳給BM25做keyword search。

## How do you decide what goes into the prompt?
  1. 根據BM25的search結果，將top matching sections的內容放入prompt中，並且在prompt中加入使用者的query，讓LLM能夠根據這些資訊來生成答案。

## How do you cite sources so users can inspect the original Markdown?
  1. 在回答中，我會在相關的部分引用原始Markdown文件的名稱和對應的section標題，讓使用者可以根據這些信息去查看原始文件中的內容。

## What should happen when retrieval finds weak or irrelevant results?
  1. 如果檢索到的結果與使用者的問題不相關或質量較差，應該在回答中明確指出這一點，並建議使用者重新表達問題或提供更多上下文信息以獲得更準確的答案。

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