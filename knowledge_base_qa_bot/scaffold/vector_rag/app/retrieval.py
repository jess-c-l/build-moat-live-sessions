import os

from langchain.schema import HumanMessage, SystemMessage

from . import indexer


SYSTEM_PROMPT = """You are a knowledge base Q&A assistant. Answer the user's QUESTION using ONLY the information in the CONTEXT below.

Rules:
1. Use ONLY facts that appear in the CONTEXT. Do NOT use any outside knowledge, and do NOT guess or infer beyond what the text states.
2. Every claim in your answer must be backed by a citation in the exact format [Source: filename#heading]. Cite only source IDs that literally appear in a [Source: ...] line within the CONTEXT — never invent, modify, or combine IDs.
3. If the CONTEXT does not contain enough information to answer the QUESTION, reply with exactly:
   I cannot confirm from the knowledge base.
   Do not add citations or any other text in that case.
4. Keep answers concise and grounded strictly in the cited sources."""

# Optional retrieval distance ceiling (FAISS L2: smaller = closer). Chunks
# farther than this are dropped as irrelevant. Disabled (None) by default;
# set MAX_DISTANCE after calibrating against real queries.
_raw_max_distance = os.getenv("MAX_DISTANCE")
MAX_DISTANCE = float(_raw_max_distance) if _raw_max_distance else None

_llm = None


def get_llm():
    """Build the chat model. Switch provider with LLM_PROVIDER=openai|google."""
    global _llm
    if _llm is None:
        provider = os.getenv("LLM_PROVIDER", "openai").lower()
        if provider == "google":
            from langchain_google_genai import ChatGoogleGenerativeAI

            _llm = ChatGoogleGenerativeAI(
                model=os.getenv("GOOGLE_MODEL", "gemini-2.5-flash"),
                timeout=20,
                max_retries=1,
            )
        else:
            from langchain_openai import ChatOpenAI

            _llm = ChatOpenAI(
                model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                request_timeout=20,
                max_retries=1,
            )
    return _llm


def build_prompt(query: str, ranked_chunks: list) -> str:
    blocks = []
    for doc, _score in ranked_chunks:
        blocks.append(
            f"[Source: {doc.metadata.get('source', 'unknown')}]\n"
            f"Heading path: {doc.metadata.get('heading', 'unknown')}\n"
            f"{doc.page_content}"
        )
    context = "\n\n".join(blocks) if blocks else "(no context)"
    return f"CONTEXT:\n{context}\n\nQUESTION:\n{query}"


def query(question: str) -> dict:
    if indexer.vectorstore is None:
        return {
            "answer": "The knowledge base has not been indexed yet. Call POST /index first.",
            "sources": [],
        }

    ranked_chunks = indexer.search(question, k=3)

    # Optional score threshold: drop chunks beyond MAX_DISTANCE (too far to
    # be relevant). If everything is filtered out, answer honestly.
    if MAX_DISTANCE is not None:
        ranked_chunks = [
            (doc, score) for doc, score in ranked_chunks
            if float(score) <= MAX_DISTANCE
        ]

    if not ranked_chunks:
        return {
            "answer": "I cannot confirm from the knowledge base.",
            "sources": [],
        }

    sources = [
        {
            "source": doc.metadata.get("source", "unknown"),
            "heading": doc.metadata.get("heading", "unknown"),
            "score": round(float(score), 3),
            "content": doc.page_content[:240],
        }
        for doc, score in ranked_chunks
    ]

    try:
        response = get_llm().invoke([
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=build_prompt(question, ranked_chunks)),
        ])
    except Exception as e:
        provider = os.getenv("LLM_PROVIDER", "openai").lower()
        key_hint = (
            "GOOGLE_API_KEY and the Google AI Studio quota"
            if provider == "google"
            else "OPENAI_API_KEY and the OpenAI account quota/billing"
        )
        return {
            "answer": (
                "Failed to generate an answer because the language model call failed: "
                f"{type(e).__name__}: {e}. "
                f"Retrieval succeeded (see sources below); check the {key_hint}."
            ),
            "sources": sources,
        }

    return {
        "answer": response.content,
        "sources": sources,
    }
