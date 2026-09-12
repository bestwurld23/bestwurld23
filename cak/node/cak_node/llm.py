"""Answer generators.

Generation is kept behind a narrow protocol so retrieval and the citation lock
can be tested without a model on the box (PRD §21.3), and so Phase 0 ships with
an extractive stub while Phase 1 swaps in a local GGUF via Ollama (PRD §18).

Neither generator is trusted. Whatever comes out of here goes through
:mod:`cak_node.grounding` before a resident ever sees it.
"""

from __future__ import annotations

import json
import re
from typing import Protocol, runtime_checkable

from cak_node.retrieval import Hit
from cak_node.text import tokenize

# Normative system prompt, PRD §6.3, reproduced word for word. Served verbatim
# at GET /agent/prompt so an auditor can read what the node was told to do.
SYSTEM_PROMPT = (
    "You are a civic information clerk. You only state facts present in the provided "
    "official excerpts.\n"
    "You do not decide who may vote. You do not give partisan advice.\n"
    "You do not guess. If the excerpts are insufficient, say you don't know and give "
    "the election office contact from the locale pack.\n"
    "Always return citations."
)

MAX_EXCERPT_CHARS = 320

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|\n")


@runtime_checkable
class Generator(Protocol):
    """Turns a question plus excerpts into markdown. Must not add facts."""

    name: str

    def generate(self, question: str, hits: list[Hit], language: str) -> str: ...

    @property
    def model_loaded(self) -> bool: ...


def best_excerpt(text: str, question: str, max_chars: int = MAX_EXCERPT_CHARS) -> str:
    """Pick the passage of ``text`` most relevant to ``question``.

    Citations quote the file, so the excerpt has to be the part a reader would
    check, not the first N characters of whatever chunk matched.
    """
    query_tokens = set(tokenize(question))
    sentences = [s.strip() for s in _SENTENCE_RE.split(text) if s.strip()]
    if not sentences:
        return text[:max_chars].strip()

    scored = [
        (len(query_tokens & set(tokenize(s))), -index, index, s)
        for index, s in enumerate(sentences)
    ]
    scored.sort(reverse=True)
    best_index = scored[0][2]

    # Grow outward from the best sentence until the budget is spent, so the
    # excerpt keeps its surrounding context.
    selected = [best_index]
    length = len(sentences[best_index])
    low, high = best_index - 1, best_index + 1
    while length < max_chars and (low >= 0 or high < len(sentences)):
        if high < len(sentences) and length + len(sentences[high]) + 1 <= max_chars:
            selected.append(high)
            length += len(sentences[high]) + 1
            high += 1
        elif low >= 0 and length + len(sentences[low]) + 1 <= max_chars:
            selected.append(low)
            length += len(sentences[low]) + 1
            low -= 1
        else:
            break
    selected.sort()
    excerpt = " ".join(sentences[i] for i in selected).strip()
    return excerpt[:max_chars].rstrip()


class ExtractiveGenerator:
    """Phase 0 default: quotes the official files and adds nothing.

    This is not a placeholder to be ashamed of. On a Pi with no model loaded it
    still satisfies G1 — a cited answer about where and when to participate —
    and it cannot hallucinate, because every word it emits came off disk.
    """

    name = "extractive"

    def __init__(self, max_sections: int = 3) -> None:
        self.max_sections = max_sections

    @property
    def model_loaded(self) -> bool:
        """False, truthfully: there is no model. The node is still healthy.

        Reporting True here would be convenient and dishonest, and it would
        destroy the signal a steward needs after switching to ``ollama`` —
        where False means the model really is missing.
        """
        return False

    def generate(self, question: str, hits: list[Hit], language: str) -> str:
        lines: list[str] = []
        seen: set[tuple[str, str]] = set()
        for hit in hits[: self.max_sections]:
            key = (hit.chunk.file_id, hit.chunk.locator)
            if key in seen:
                continue
            seen.add(key)
            excerpt = best_excerpt(hit.chunk.text, question)
            lines.append(f"**{hit.chunk.title}** ({hit.chunk.file_id})")
            for para in excerpt.splitlines():
                if para.strip():
                    lines.append(f"> {para.strip()}")
            lines.append("")
        return "\n".join(lines).strip()


class OllamaGenerator:
    """Phase 1 path: a local GGUF served by Ollama on the same box.

    Still offline — Ollama runs on the node. The request never leaves the
    device, and the output is grounded-checked exactly like the stub's.
    """

    name = "ollama"

    def __init__(
        self,
        model: str,
        host: str = "http://127.0.0.1:11434",
        timeout: float = 120.0,
    ) -> None:
        self.model = model
        self.host = host.rstrip("/")
        self.timeout = timeout

    @property
    def model_loaded(self) -> bool:
        try:
            import httpx
        except ImportError:
            return False
        try:
            reply = httpx.get(f"{self.host}/api/tags", timeout=2.0)
            reply.raise_for_status()
            names = {m.get("name", "") for m in reply.json().get("models", [])}
        except Exception:  # noqa: BLE001 - any failure means "no model here"
            return False
        return any(n == self.model or n.startswith(f"{self.model}:") for n in names)

    def generate(self, question: str, hits: list[Hit], language: str) -> str:
        import httpx

        excerpts = "\n\n".join(
            f"[{i + 1}] file_id={h.chunk.file_id} locator={h.chunk.locator} "
            f"title={h.chunk.title}\n{h.chunk.text}"
            for i, h in enumerate(hits)
        )
        user = (
            f"Answer in language code: {language}\n\n"
            f"Question: {question}\n\n"
            f"Official excerpts (the only permitted source):\n{excerpts}\n\n"
            "Answer in at most four short sentences, grade-6 reading level. "
            "Use only facts from the excerpts. Do not add phone numbers, times, "
            "dates or addresses that are not in the excerpts."
        )
        reply = httpx.post(
            f"{self.host}/api/chat",
            timeout=self.timeout,
            json={
                "model": self.model,
                "stream": False,
                "options": {"temperature": 0.0},
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user},
                ],
            },
        )
        reply.raise_for_status()
        payload = reply.json()
        return str(payload.get("message", {}).get("content", "")).strip()

    def __repr__(self) -> str:
        return f"OllamaGenerator(model={self.model!r}, host={self.host!r})"


def build_generator(kind: str, model: str, host: str = "http://127.0.0.1:11434") -> Generator:
    """Construct the generator named in ``node.toml``."""
    if kind == "extractive":
        return ExtractiveGenerator()
    if kind == "ollama":
        return OllamaGenerator(model=model, host=host)
    raise ValueError(f"unknown generator {kind!r}; expected 'extractive' or 'ollama'")


def describe_prompt() -> str:
    """The exact system prompt, exposed so stewards and auditors can read it."""
    return json.dumps({"system_prompt": SYSTEM_PROMPT}, indent=2)
