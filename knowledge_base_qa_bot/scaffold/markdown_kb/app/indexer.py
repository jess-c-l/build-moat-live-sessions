import math
import re
from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path


DOCS_DIR = Path(__file__).resolve().parents[3] / "docs"
INDEX_PATH = Path(__file__).resolve().parents[3] / ".kb" / "index.json"
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
TOKEN_RE = re.compile(r"[a-z0-9]+")
STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "can",
    "do",
    "does",
    "for",
    "from",
    "how",
    "i",
    "is",
    "it",
    "my",
    "of",
    "the",
    "to",
    "what",
    "when",
    "which",
}


@dataclass
class Section:
    id: str
    file: str
    heading: str
    heading_path: list[str]
    content: str
    tokens: list[str]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "file": self.file,
            "heading": self.heading,
            "heading_path": self.heading_path,
            "content": self.content,
            "tokens": self.tokens,
        }


sections: list[Section] = []
doc_freq: Counter[str] = Counter()
avg_doc_len = 0.0
files_indexed = 0


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "section"


def tokenize(text: str) -> list[str]:
    return [t for t in TOKEN_RE.findall(text.lower()) if t not in STOP_WORDS]


def parse_markdown(path: Path) -> list[Section]:
    file = path.name
    text = path.read_text(encoding="utf-8")

    result: list[Section] = []
    heading_stack: list[tuple[int, str]] = []
    current_heading: str | None = None
    current_path: list[str] = []
    current_content: list[str] = []

    def emit(heading: str, hpath: list[str], content_lines: list[str]) -> None:
        content = "\n".join(content_lines).strip()
        tokens = tokenize(heading + " " + content)
        result.append(Section(
            id=f"{file}#{slugify(heading)}",
            file=file,
            heading=heading,
            heading_path=hpath,
            content=content,
            tokens=tokens,
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


def write_index_json(index_path: Path = INDEX_PATH) -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "sections": [s.to_dict() for s in sections],
        "stats": {
            "files_indexed": files_indexed,
            "avg_doc_len": avg_doc_len,
        },
    }
    index_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def rebuild_stats() -> None:
    global doc_freq, avg_doc_len, files_indexed

    files_indexed = len({s.file for s in sections})

    df: Counter[str] = Counter()
    for s in sections:
        for token in set(s.tokens):
            df[token] += 1
    doc_freq = df

    total_len = sum(len(s.tokens) for s in sections)
    avg_doc_len = total_len / len(sections) if sections else 0.0


def load_index_json(index_path: Path = INDEX_PATH) -> tuple[int, int]:
    global sections

    if not index_path.exists():
        return 0, 0

    payload = json.loads(index_path.read_text(encoding="utf-8"))
    sections = [Section(**item) for item in payload["sections"]]
    rebuild_stats()
    return files_indexed, len(sections)


def build_index(docs_dir: Path = DOCS_DIR) -> tuple[int, int]:
    global sections, doc_freq, avg_doc_len, files_indexed

    # TODO: Build an in-memory section index from docs/*.md.
    #
    # Hints:
    # 1. Read all Markdown files from docs_dir.
    # 2. Call parse_markdown() for each file.
    # 3. Call rebuild_stats() to compute BM25 metadata.
    # 4. Persist .kb/index.json with write_index_json().
    # 5. Call write_index_json() so students can inspect the generated index.
    # 6. Return (files_indexed, sections_indexed).
    sections = []
    doc_freq = Counter()
    avg_doc_len = 0.0
    files_indexed = 0
    write_index_json()
    return files_indexed, len(sections)


def bm25_score(query_tokens: list[str], section: Section, k1: float = 1.5, b: float = 0.75) -> float:
    # TODO: Score one section for the query using BM25.
    #
    # Hints:
    # 1. Count term frequency in the section.
    # 2. Use doc_freq to give rare terms higher weight.
    # 3. Normalize by section length using avg_doc_len.
    # 4. Add a small boost when query terms appear in heading_path.
    return 0.0


def search(query: str, k: int = 3) -> list[tuple[Section, float]]:
    query_tokens = tokenize(query)
    ranked = [
        (section, bm25_score(query_tokens, section))
        for section in sections
    ]
    ranked.sort(key=lambda item: item[1], reverse=True)
    return [(section, score) for section, score in ranked[:k] if score > 0]
