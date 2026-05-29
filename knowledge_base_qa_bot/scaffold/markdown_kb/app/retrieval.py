import os

from langchain.schema import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from . import indexer


SYSTEM_PROMPT = """You are a knowledge base Q&A assistant. Answer the user's QUESTION using ONLY the information in the CONTEXT below.

Rules:
1. Use ONLY facts that appear in the CONTEXT. Do NOT use any outside knowledge, and do NOT guess or infer beyond what the text states.
2. Every claim in your answer must be backed by a citation in the exact format [Source: filename#heading]. Cite only source IDs that literally appear in a [Source: ...] line within the CONTEXT — never invent, modify, or combine IDs.
3. If the CONTEXT does not contain enough information to answer the QUESTION, reply with exactly:
   I cannot confirm from the knowledge base.
   Do not add citations or any other text in that case.
4. Keep answers concise and grounded strictly in the cited sources."""

_llm = None


def get_llm():
    global _llm
    if _llm is None:
        _llm = ChatOpenAI(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            request_timeout=20,
            max_retries=1,
        )
    return _llm


def build_prompt(query: str, ranked_sections: list) -> str:
    blocks = []
    for section, _score in ranked_sections:
        blocks.append(
            f"[Source: {section.id}]\n"
            f"Heading path: {' > '.join(section.heading_path)}\n"
            f"{section.content}"
        )
    context = "\n\n".join(blocks) if blocks else "(no context)"
    return f"CONTEXT:\n{context}\n\nQUESTION:\n{query}"


def query(question: str) -> dict:
    if not indexer.sections:
        return {
            "answer": "The knowledge base has not been indexed yet. Call POST /index first.",
            "sources": [],
        }

    ranked_sections = indexer.search(question, k=3)
    if not ranked_sections:
        return {
            "answer": "I cannot confirm from the knowledge base.",
            "sources": [],
        }

    response = get_llm().invoke([
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=build_prompt(question, ranked_sections)),
    ])

    sources = [
        {
            "source": section.id,
            "heading": " > ".join(section.heading_path),
            "score": round(score, 3),
            "content": section.content[:240],
        }
        for section, score in ranked_sections
    ]

    return {
        "answer": response.content,
        "sources": sources,
    }
