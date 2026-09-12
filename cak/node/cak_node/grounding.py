"""The citation lock: proof that an answer says nothing the files do not.

Normative source: PRD §6.3 steps 5-6 ("if generation includes a claim not in
chunks, strip or fail closed", "never invent phone numbers") and §16 (zero
hallucinated contact info in the test suite).

The default generator is extractive, so it passes trivially. This module exists
for the moment a real local model is wired in (Phase 1): every sentence it
emits is checked against the retrieved excerpts, and anything unsupported fails
the whole answer closed to ``i_dont_know`` rather than being served with a
citation it does not deserve.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from cak_node.retrieval import Chunk
from cak_node.text import content_tokens, tokenize

# Content-token coverage a sentence must reach against the allowed pool.
MIN_TOKEN_COVERAGE = 0.85

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
_NUMERIC_TOKEN_RE = re.compile(r"\d")
_MARKDOWN_NOISE_RE = re.compile(r"[*_`>#\[\]()|]+")


@dataclass
class GroundingResult:
    """Outcome of checking one generated answer against its excerpts."""

    ok: bool
    ungrounded_sentences: list[str] = field(default_factory=list)
    unsupported_numbers: list[str] = field(default_factory=list)

    @property
    def reason(self) -> str | None:
        if self.ok:
            return None
        parts = []
        if self.unsupported_numbers:
            parts.append(
                "numbers not present in the official excerpts: "
                + ", ".join(sorted(set(self.unsupported_numbers)))
            )
        if self.ungrounded_sentences:
            parts.append(f"{len(self.ungrounded_sentences)} unsupported sentence(s)")
        return "; ".join(parts)


def split_sentences(text: str) -> list[str]:
    cleaned = _MARKDOWN_NOISE_RE.sub(" ", text)
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(cleaned) if s.strip()]


def verify(
    answer: str,
    chunks: list[Chunk],
    extra_allowed_text: str = "",
    allowed_numbers_text: str = "",
) -> GroundingResult:
    """Check that ``answer`` is supported by ``chunks``.

    ``extra_allowed_text`` supplies vocabulary the node itself is entitled to
    use for framing (file titles, the authority's name). ``allowed_numbers_text``
    supplies the only numbers permitted beyond the excerpts — in practice the
    authority's phone and address from the pack manifest, which are official by
    construction.
    """
    if not chunks:
        return GroundingResult(ok=False, ungrounded_sentences=split_sentences(answer))

    excerpt_text = "\n".join(c.text for c in chunks)
    titles_text = " ".join(f"{c.title} {c.locator} {c.file_id}" for c in chunks)

    allowed_tokens = set(tokenize(excerpt_text))
    allowed_tokens |= set(tokenize(titles_text))
    allowed_tokens |= set(tokenize(extra_allowed_text))
    allowed_tokens |= set(tokenize(allowed_numbers_text))

    # Numbers are held to a stricter standard: they must come from the excerpts
    # or from the pack's own contact block. This is the rule that stops an
    # invented phone number or a "polls open at 3am".
    allowed_numbers = set(_numeric_tokens(excerpt_text)) | set(
        _numeric_tokens(allowed_numbers_text)
    )

    ungrounded: list[str] = []
    unsupported_numbers: list[str] = []

    for sentence in split_sentences(answer):
        tokens = content_tokens(sentence)
        for token in tokens:
            if _NUMERIC_TOKEN_RE.search(token) and token not in allowed_numbers:
                unsupported_numbers.append(token)
        if not tokens:
            continue
        supported = sum(1 for t in tokens if t in allowed_tokens)
        if supported / len(tokens) < MIN_TOKEN_COVERAGE:
            ungrounded.append(sentence)

    return GroundingResult(
        ok=not ungrounded and not unsupported_numbers,
        ungrounded_sentences=ungrounded,
        unsupported_numbers=unsupported_numbers,
    )


def _numeric_tokens(text: str) -> list[str]:
    return [t for t in tokenize(text) if _NUMERIC_TOKEN_RE.search(t)]
