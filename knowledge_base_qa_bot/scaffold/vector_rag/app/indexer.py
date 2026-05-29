import json
import os
import re
import shutil
from pathlib import Path

from langchain.schema import Document
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS


DOCS_DIR = Path(__file__).resolve().parents[3] / "docs"
INDEX_DIR = Path(__file__).resolve().parents[3] / ".kb" / "faiss_index"
OPENAI_EMBEDDING_MODEL = "text-embedding-3-small"
GOOGLE_EMBEDDING_MODEL = "models/gemini-embedding-001"
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")

# TODO: Configure chunking parameters for traditional RAG.
#
# Design decision: Balance semantic recall against context noise.
#
# Hints:
# 1. chunk_size around 500 chars is a reasonable prototype default.
# 2. chunk_overlap helps avoid cutting facts at boundaries.
# 3. separators should prefer Markdown structure before individual words.
splitter = RecursiveCharacterTextSplitter(
    chunk_size=500,
    chunk_overlap=0,
    separators=["\n\n", "\n", ". ", " "],
)

vectorstore: FAISS | None = None
_embeddings = None
files_indexed = 0
sections_indexed = 0


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "section"


def _embedding_config() -> tuple[str, str]:
    """Return (provider, model). Switch with LLM_PROVIDER=openai|google."""
    provider = os.getenv("LLM_PROVIDER", "openai").lower()
    if provider == "google":
        return "google", os.getenv("GOOGLE_EMBEDDING_MODEL", GOOGLE_EMBEDDING_MODEL)
    return "openai", os.getenv("OPENAI_EMBEDDING_MODEL", OPENAI_EMBEDDING_MODEL)


def embedding_model_id() -> str:
    """Stable id stored in metadata so a provider/model swap invalidates the index."""
    provider, model = _embedding_config()
    return f"{provider}:{model}"


def get_embeddings():
    global _embeddings
    if _embeddings is None:
        provider, model = _embedding_config()
        if provider == "google":
            if not os.getenv("GOOGLE_API_KEY"):
                raise RuntimeError("GOOGLE_API_KEY is not set in the server environment")
            from langchain_google_genai import GoogleGenerativeAIEmbeddings

            _embeddings = GoogleGenerativeAIEmbeddings(model=model)
        else:
            if not os.getenv("OPENAI_API_KEY"):
                raise RuntimeError("OPENAI_API_KEY is not set in the server environment")
            from langchain_openai import OpenAIEmbeddings

            _embeddings = OpenAIEmbeddings(
                model=model,
                request_timeout=20,
                max_retries=1,
            )
    return _embeddings


def load_markdown_sections(path: Path) -> list[Document]:
    """Split one Markdown file into heading sections as citable Documents.

    Each section keeps filename#heading metadata so chunks stay traceable
    back to the original Markdown even after the text splitter runs.
    """
    file = path.name
    text = path.read_text(encoding="utf-8")

    result: list[Document] = []
    heading_stack: list[tuple[int, str]] = []
    current_heading: str | None = None
    current_path: list[str] = []
    current_content: list[str] = []

    def emit(heading: str, hpath: list[str], content_lines: list[str]) -> None:
        content = "\n".join(content_lines).strip()
        heading_path = " > ".join(hpath)
        # Put the heading path into page_content too: heading words are a
        # strong semantic signal and improve embedding recall.
        page_content = f"{heading_path}\n{content}" if content else heading_path
        result.append(Document(
            page_content=page_content,
            metadata={
                "source": f"{file}#{slugify(heading)}",
                "heading": heading_path,
            },
        ))

    for line in text.splitlines():
        m = HEADING_RE.match(line)
        if m:
            if current_heading is not None:
                emit(current_heading, current_path, current_content)
            level = len(m.group(1))
            heading = m.group(2).strip()
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, heading))
            current_heading = heading
            current_path = [h for _, h in heading_stack]
            current_content = []
        elif current_heading is not None:
            current_content.append(line)

    if current_heading is not None:
        emit(current_heading, current_path, current_content)

    return result


def build_index(docs_dir: Path = DOCS_DIR) -> tuple[int, int]:
    global vectorstore, files_indexed, sections_indexed

    all_sections: list[Document] = []
    seen_files: set[str] = set()
    for md in sorted(docs_dir.glob("*.md")):
        sections = load_markdown_sections(md)
        if sections:
            all_sections.extend(sections)
            seen_files.add(md.name)

    files_indexed = len(seen_files)

    if not all_sections:
        # Nothing to index: drop the in-memory store and clear stale files.
        vectorstore = None
        sections_indexed = 0
        save_vector_index()
        return files_indexed, sections_indexed

    # Section -> ~500-char chunks; metadata (source/heading) propagates.
    chunks = splitter.split_documents(all_sections)
    sections_indexed = len(chunks)

    # Embeds every chunk via the OpenAI embeddings API.
    vectorstore = FAISS.from_documents(chunks, get_embeddings())
    save_vector_index()
    return files_indexed, sections_indexed


def save_vector_index(index_dir: Path = INDEX_DIR) -> None:
    """Persist the FAISS index so a restart does not require re-embedding."""
    if vectorstore is None or sections_indexed == 0:
        # Remove any stale persisted index so startup will not load it.
        shutil.rmtree(index_dir, ignore_errors=True)
        return

    index_dir.mkdir(parents=True, exist_ok=True)
    vectorstore.save_local(str(index_dir))

    metadata = {
        "embedding_model": embedding_model_id(),
        "files_indexed": files_indexed,
        "sections_indexed": sections_indexed,
    }
    (index_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )


def load_vector_index(index_dir: Path = INDEX_DIR) -> tuple[int, int]:
    """Load a persisted FAISS index on startup so /chat works without /index."""
    global vectorstore, files_indexed, sections_indexed

    faiss_file = index_dir / "index.faiss"
    pkl_file = index_dir / "index.pkl"
    metadata_file = index_dir / "metadata.json"
    if not (faiss_file.exists() and pkl_file.exists()):
        return 0, 0

    files = 0
    chunks = 0
    if metadata_file.exists():
        metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
        # Embeddings must match: vectors built with one model are not
        # comparable to query vectors from another. Force a re-index instead.
        if metadata.get("embedding_model") != embedding_model_id():
            return 0, 0
        files = metadata.get("files_indexed", 0)
        chunks = metadata.get("sections_indexed", 0)

    # allow_dangerous_deserialization is safe ONLY because this index.pkl was
    # produced by this local app; never load an untrusted pickle this way.
    vectorstore = FAISS.load_local(
        str(index_dir),
        get_embeddings(),
        allow_dangerous_deserialization=True,
    )
    files_indexed = files
    sections_indexed = chunks
    return files_indexed, sections_indexed


def search(query: str, k: int = 3) -> list[tuple[Document, float]]:
    if vectorstore is None:
        return []
    return vectorstore.similarity_search_with_score(query, k=k)
