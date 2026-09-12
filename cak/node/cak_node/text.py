"""Tokenization shared by retrieval and the citation lock.

Both modules have to agree on what a "content word" is: retrieval uses it to
decide whether a chunk is about the question at all, and the citation lock uses
it to decide whether a sentence is supported. If the two definitions drifted,
an answer could pass the lock on words retrieval never matched.
"""

from __future__ import annotations

import re

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
_SLUG_STRIP_RE = re.compile(r"[^a-z0-9]+")

# Prefix matching applies from this length up, so "hours" matches "hour" and
# "site" matches "sites" without dragging in a stemmer.
MIN_PREFIX_LEN = 4

# Function words carry no claim and cannot distinguish one official document
# from another.
FUNCTION_WORDS: frozenset[str] = frozenset(
    """
    a an the and or but if then than that this these those there here of in on at to from by for
    with without into over under about as is are was were be been being am do does did doing have
    has had having you your yours i me my we our us it its they them their he she his her not no
    can could may might must shall should will would per also please see note according states
    said says only same both each any all more most some such via when where what which who whom
    how why while during before after between up down out off again further once because so
    """.split()
)


def tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric tokens, matching the FTS5 unicode61 tokenizer."""
    return _TOKEN_RE.findall(text.lower())


def content_tokens(text: str) -> list[str]:
    """Tokens that can carry a claim or identify a topic."""
    return [t for t in tokenize(text) if t not in FUNCTION_WORDS]


def slugify(text: str) -> str:
    return _SLUG_STRIP_RE.sub("-", text.lower()).strip("-")


# Suffixes stripped to a fixed point by :func:`stem`. Longest first so "ies"
# wins over "es" and "s" on the same word.
_SUFFIXES: tuple[str, ...] = ("ing", "ies", "ied", "es", "ed", "er", "s", "e", "y")
MIN_STEM_LEN = 3


def stem(token: str) -> str:
    """Crude suffix stripping, iterated until it stops changing.

    Not linguistics — consistency. "polls" and "polling" must land on the same
    string or a question about poll closing times misses the section titled
    "Election day hours", and the resident gets "I don't know" for a question
    the files answer. Iterating to a fixed point is what makes the function
    idempotent, so "addresses" and "address" agree.

    The cost is occasional over-stemming ("closure" and "closed" do not meet).
    That direction of error is acceptable: it loses recall, never grounding —
    stems are used to find candidate passages, never to decide whether an
    answer is supported.
    """
    current = token
    while True:
        for suffix in _SUFFIXES:
            if current.endswith(suffix) and len(current) - len(suffix) >= MIN_STEM_LEN:
                current = current[: -len(suffix)]
                break
        else:
            return current


def token_present(needle: str, haystack: set[str]) -> bool:
    """True when ``needle`` appears in ``haystack``, by stem or by prefix.

    "hours" finds "hour", "polls" finds "polling", but "id" must not find
    "identification" — hence the length floor on prefix matching.
    """
    if needle in haystack:
        return True
    needle_stem = stem(needle)
    for token in haystack:
        if stem(token) == needle_stem:
            return True
        if len(needle) >= MIN_PREFIX_LEN and token.startswith(needle):
            return True
    return False


def coverage(query: str, text: str, include_function_words: bool = False) -> float:
    """Fraction of the question's words that ``text`` actually contains.

    By default only content words count, since "the" and "is" say nothing about
    what a passage is about. Pass ``include_function_words=True`` when matching
    against a *heading*: official documents title their sections in the shape of
    the question ("Where to vote", "How to register"), so there the
    interrogative is the most discriminating word in the query, not the least.

    Returns 1.0 for a question with nothing to match on.
    """
    words = tokenize(query) if include_function_words else content_tokens(query)
    needles = set(words)
    if not needles:
        return 1.0
    haystack = set(tokenize(text))
    hits = sum(1 for needle in needles if token_present(needle, haystack))
    return hits / len(needles)


def term_frequency(query: str, text: str) -> int:
    """How many times the question's content words occur in ``text``."""
    needles = {stem(t) for t in content_tokens(query)}
    if not needles:
        return 0
    return sum(1 for token in tokenize(text) if stem(token) in needles)
