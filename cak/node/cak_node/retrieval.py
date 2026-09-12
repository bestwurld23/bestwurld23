"""Chunking and BM25 retrieval over the pack's ``official/`` directory.

Normative source: PRD §6.3 steps 1-3 and §12.1 (SQLite FTS5 for v1, no cloud
vector database). Retrieval is deliberately isolated from generation so the
tests can stub the model (PRD §21.3).

Nothing outside ``official/`` is ever indexed. That is the whole point: the
agent's knowledge is the steward's file set, not the model's weights.
"""

from __future__ import annotations

import re
import sqlite3
import threading
from dataclasses import dataclass

from cak_node.pack import LocalePack, OfficialFile
from cak_node.text import MIN_STEM_LEN, coverage, slugify, stem, term_frequency, tokenize

# Scoring
# -------
# FTS5's bm25() selects candidates, but it does *not* set the score a pack
# thresholds on. BM25's IDF term assumes a large corpus: in a pack of three
# documents and ten chunks, a phrase like "early voting" appears in most of
# them, IDF collapses toward zero, and every chunk — including the exactly
# right one — scores 0.0. A locale pack is 3 to 300 documents by design
# (PRD §10), so that is the normal case here, not an edge case.
#
# So the score is built from question *coverage* instead, which is stable at
# any corpus size and means something a pack maintainer can reason about:
# "how much of what was asked does this passage actually address?"
#
#     score = coverage * (BASE + TITLE_BONUS * title_coverage
#                              + DENSITY_BONUS * term_density)
#
# With the default retrieval_min_score of 0.35, a passage must carry roughly
# half the question's content words to be answerable at all. BM25 is kept on
# each Hit for diagnostics.
SCORE_BASE = 0.70
TITLE_BONUS = 0.20
DENSITY_BONUS = 0.10
DENSITY_SATURATION = 3.0

BM25_TITLE_WEIGHT = 2.0
BM25_TEXT_WEIGHT = 1.0

# How many BM25 candidates to rescore before taking the top_k best.
CANDIDATE_MULTIPLIER = 6
MIN_CANDIDATES = 30

TARGET_CHUNK_CHARS = 900
CSV_ROWS_PER_CHUNK = 25


@dataclass(frozen=True)
class Chunk:
    """A retrievable span of one official file."""

    file_id: str
    title: str
    locator: str
    text: str


@dataclass(frozen=True)
class Hit:
    """A retrieved chunk with its normalized score."""

    chunk: Chunk
    score: float
    raw_bm25: float
    coverage: float = 1.0


class PdfTextUnavailable(RuntimeError):
    """Raised when a PDF is present but no extractor is installed."""


# --------------------------------------------------------------------------- #
# Chunking
# --------------------------------------------------------------------------- #
def chunk_markdown(file: OfficialFile, text: str) -> list[Chunk]:
    """Split on headings, then pack paragraphs up to ~TARGET_CHUNK_CHARS.

    Each chunk's title is the full heading path — "Where to vote — Springfield
    Library", not just "Springfield Library". The document-level heading is
    usually the part that says what the file is *about*, and dropping it loses
    both retrieval signal and the context a reader needs to trust a citation.

    Locators are heading anchors (``#election-day-hours``) so a citation points
    at something findable on the page.
    """
    chunks: list[Chunk] = []
    heading_path: list[str] = []
    buffer: list[str] = []
    start_line = 1

    def current_title() -> str:
        return " — ".join(heading_path) if heading_path else file.title

    def current_anchor() -> str:
        return slugify(heading_path[-1]) if heading_path else ""

    def flush(end_line: int, title: str, anchor: str) -> None:
        body = "\n".join(buffer).strip()
        if not body:
            return
        chunks.append(
            Chunk(
                file_id=file.file_id,
                title=title,
                locator=f"#{anchor}" if anchor else f"L{start_line}-L{end_line}",
                text=body,
            )
        )

    lines = text.splitlines()
    for lineno, line in enumerate(lines, start=1):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            flush(lineno - 1, current_title(), current_anchor())
            buffer = []
            start_line = lineno
            level = len(stripped) - len(stripped.lstrip("#"))
            heading = stripped.lstrip("#").strip()
            if heading:
                del heading_path[max(level - 1, 0) :]
                heading_path.append(heading)
            continue
        buffer.append(line)
        if sum(len(x) + 1 for x in buffer) >= TARGET_CHUNK_CHARS and not line.strip():
            flush(lineno, current_title(), current_anchor())
            buffer = []
            start_line = lineno + 1
    flush(len(lines), current_title(), current_anchor())
    return chunks


def chunk_csv(file: OfficialFile, text: str) -> list[Chunk]:
    """Keep the header row with every chunk so a row stays readable alone."""
    rows = [r for r in text.splitlines() if r.strip()]
    if not rows:
        return []
    header, body = rows[0], rows[1:]
    if not body:
        return [Chunk(file.file_id, file.title, "row 1", header)]
    chunks: list[Chunk] = []
    for start in range(0, len(body), CSV_ROWS_PER_CHUNK):
        window = body[start : start + CSV_ROWS_PER_CHUNK]
        first, last = start + 2, start + 1 + len(window)
        chunks.append(
            Chunk(
                file_id=file.file_id,
                title=file.title,
                locator=f"rows {first}-{last}" if last > first else f"row {first}",
                text="\n".join([header, *window]),
            )
        )
    return chunks


def chunk_html(file: OfficialFile, text: str) -> list[Chunk]:
    stripped = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", text)
    stripped = re.sub(r"(?s)<[^>]+>", " ", stripped)
    stripped = re.sub(r"\s+", " ", stripped).strip()
    return _pack_plain(file, stripped, locator_kind="section")


def chunk_pdf(file: OfficialFile) -> list[Chunk]:
    """One chunk per page, locator ``p.N``. Requires the ``pdf`` extra."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise PdfTextUnavailable(
            f"cannot extract text from {file.file_id}: install the 'pdf' extra (pypdf)"
        ) from exc
    reader = PdfReader(str(file.path))
    chunks: list[Chunk] = []
    for page_no, page in enumerate(reader.pages, start=1):
        body = (page.extract_text() or "").strip()
        if body:
            chunks.append(Chunk(file.file_id, file.title, f"p.{page_no}", body))
    return chunks


def _pack_plain(file: OfficialFile, text: str, locator_kind: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    words = text.split()
    buffer: list[str] = []
    index = 1
    for word in words:
        buffer.append(word)
        if sum(len(w) + 1 for w in buffer) >= TARGET_CHUNK_CHARS:
            chunks.append(
                Chunk(file.file_id, file.title, f"{locator_kind} {index}", " ".join(buffer))
            )
            buffer = []
            index += 1
    if buffer:
        chunks.append(Chunk(file.file_id, file.title, f"{locator_kind} {index}", " ".join(buffer)))
    return chunks


def chunk_file(file: OfficialFile) -> list[Chunk]:
    """Dispatch to the right chunker for one official file."""
    suffix = file.path.suffix.lower()
    if suffix == ".pdf":
        return chunk_pdf(file)
    text = file.path.read_text(encoding="utf-8", errors="replace")
    if suffix == ".md":
        return chunk_markdown(file, text)
    if suffix == ".csv":
        return chunk_csv(file, text)
    if suffix in {".html", ".htm"}:
        return chunk_html(file, text)
    return _pack_plain(file, text, locator_kind="section")


# --------------------------------------------------------------------------- #
# Index
# --------------------------------------------------------------------------- #
class OfficialIndex:
    """An FTS5 index over exactly one pack's official files.

    The index lives in a private in-memory database and is rebuilt whenever the
    steward replaces files, so there is no way for a stale index to keep serving
    a document that is no longer on the node.
    """

    def __init__(self) -> None:
        # A single connection shared by every request thread. SQLite connection
        # objects are not safe for concurrent use even for reads, and a rebuild
        # drops the table out from under any search in flight, so both go
        # through one lock.
        self._lock = threading.Lock()
        self._db = sqlite3.connect(":memory:", check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._create_schema()
        self.chunk_count = 0
        self.file_count = 0
        self.skipped: list[str] = []

    def _create_schema(self) -> None:
        self._db.executescript(
            """
            DROP TABLE IF EXISTS chunks;
            CREATE VIRTUAL TABLE chunks USING fts5(
                file_id UNINDEXED,
                title,
                locator UNINDEXED,
                text,
                tokenize = 'unicode61 remove_diacritics 2'
            );
            """
        )
        self._db.commit()

    def rebuild(self, pack: LocalePack) -> None:
        """Re-index the pack from disk. Safe to call on every steward write."""
        files = pack.official_files()
        prepared: list[tuple[str, list[Chunk]]] = []
        skipped: list[str] = []
        for file in files:
            try:
                chunks = chunk_file(file)
            except (PdfTextUnavailable, OSError, UnicodeError) as exc:
                skipped.append(f"{file.file_id}: {exc}")
                continue
            if not chunks:
                skipped.append(f"{file.file_id}: no extractable text")
                continue
            prepared.append((file.file_id, chunks))

        # Read and parse outside the lock; swap the index contents inside it, so
        # a concurrent search never sees a half-built table.
        with self._lock:
            self._create_schema()
            for _, chunks in prepared:
                self._db.executemany(
                    "INSERT INTO chunks (file_id, title, locator, text) VALUES (?, ?, ?, ?)",
                    [(c.file_id, c.title, c.locator, c.text) for c in chunks],
                )
            self._db.commit()
            self.chunk_count = sum(len(chunks) for _, chunks in prepared)
            self.file_count = len(prepared)
            self.skipped = skipped

    def search(self, query: str, top_k: int = 5) -> list[Hit]:
        """Search the pack. Returns at most ``top_k`` hits, best first.

        Chunks that share no content word with the question are dropped
        outright, however well BM25 scores them.
        """
        match = build_match_expression(query)
        if not match:
            return []
        try:
            with self._lock:
                rows = self._db.execute(
                    """
                    SELECT file_id, title, locator, text,
                           bm25(chunks, 0.0, ?, 0.0, ?) AS score
                    FROM chunks
                    WHERE chunks MATCH ?
                    ORDER BY score
                    LIMIT ?
                    """,
                    (
                        BM25_TITLE_WEIGHT,
                        BM25_TEXT_WEIGHT,
                        match,
                        max(top_k * CANDIDATE_MULTIPLIER, MIN_CANDIDATES),
                    ),
                ).fetchall()
        except sqlite3.OperationalError:
            # A pathological query that still parsed into bad FTS syntax is a
            # miss, not a 500: the caller turns an empty result into I_DONT_KNOW.
            return []

        hits: list[Hit] = []
        for row in rows:
            chunk = Chunk(
                file_id=row["file_id"],
                title=row["title"],
                locator=row["locator"],
                text=row["text"],
            )
            score, chunk_coverage = score_chunk(query, chunk)
            if chunk_coverage <= 0.0:
                continue
            hits.append(
                Hit(
                    chunk=chunk,
                    score=score,
                    raw_bm25=float(row["score"]),
                    coverage=chunk_coverage,
                )
            )
        hits.sort(key=lambda h: (h.score, -h.raw_bm25), reverse=True)
        return hits[:top_k]

    def close(self) -> None:
        with self._lock:
            self._db.close()


def score_chunk(query: str, chunk: Chunk) -> tuple[float, float]:
    """Score one chunk against a question. Returns ``(score, coverage)``.

    A chunk with zero coverage is not a weak answer, it is a different subject;
    the caller drops it rather than ranking it.
    """
    body = f"{chunk.title}\n{chunk.text}"
    chunk_coverage = coverage(query, body)
    if chunk_coverage <= 0.0:
        return 0.0, 0.0
    title_coverage = coverage(query, chunk.title, include_function_words=True)
    frequency = term_frequency(query, body)
    density = frequency / (frequency + DENSITY_SATURATION)
    score = chunk_coverage * (SCORE_BASE + TITLE_BONUS * title_coverage + DENSITY_BONUS * density)
    return min(score, 1.0), chunk_coverage


def build_match_expression(query: str) -> str:
    """Turn free text into a safe FTS5 MATCH expression.

    Tokens are stripped to alphanumerics, so no user input can inject FTS
    operators. Each token is searched by its stem prefix ("voting" -> "vot*"),
    which is what lets the candidate set include a passage that says "polling
    places" when the question says "polls".
    """
    tokens = tokenize(query)[:24]
    if not tokens:
        return ""
    parts: list[str] = []
    for token in tokens:
        root = stem(token)
        parts.append(f"{root}*" if len(root) >= MIN_STEM_LEN else token)
    return " OR ".join(dict.fromkeys(parts))
