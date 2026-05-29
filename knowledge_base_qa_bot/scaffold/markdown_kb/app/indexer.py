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
    global sections

    new_sections: list[Section] = []
    for md in sorted(docs_dir.glob("*.md")):
        new_sections.extend(parse_markdown(md))
    sections = new_sections

    rebuild_stats()
    write_index_json()
    return files_indexed, len(sections)


def bm25_score(query_tokens: list[str], section: Section, k1: float = 1.5, b: float = 0.75) -> float:
    if not sections or not query_tokens:
        return 0.0

    N = len(sections)
    doc_len = len(section.tokens)
    tf_counter = Counter(section.tokens)
    heading_tokens = set(tokenize(" ".join(section.heading_path)))

    score = 0.0
    for token in query_tokens:
        df = doc_freq.get(token, 0)
        if df == 0:
            continue
        idf = math.log((N - df + 0.5) / (df + 0.5) + 1)
        tf = tf_counter.get(token, 0)
        denom = tf + k1 * (1 - b + b * doc_len / avg_doc_len) if avg_doc_len else tf + k1
        if denom > 0:
            score += idf * (tf * (k1 + 1)) / denom
        if token in heading_tokens:
            score += 0.5 * idf

    return score


def search(query: str, k: int = 3) -> list[tuple[Section, float]]:
    query_tokens = tokenize(query)
    ranked = [
        (section, bm25_score(query_tokens, section))
        for section in sections
    ]
    ranked.sort(key=lambda item: item[1], reverse=True)
    return [(section, score) for section, score in ranked[:k] if score > 0]
