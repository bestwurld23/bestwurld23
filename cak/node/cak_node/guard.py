"""Scope guard: the questions this node must refuse to answer even when it could.

Normative source: PRD §2.2 (non-goals), §6.3 (never guess), §19 (UX copy).

Some refusals are *not* retrieval failures. "Am I eligible if I have a felony?"
may well hit ``contacts.md`` with a high BM25 score, and answering it from
those excerpts would still be an eligibility determination — which CAK does not
make. So the guard runs before retrieval and wins over it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class RefusalCategory(StrEnum):
    """Why a question was refused, for counters and steward review."""

    ELIGIBILITY = "eligibility"
    PARTISAN = "partisan"
    INJECTION = "injection"
    BALLOT_SECRECY = "ballot_secrecy"
    TALLY_OR_CASTING = "tally_or_casting"


@dataclass(frozen=True)
class Refusal:
    """A guard decision. ``message_key`` selects the i18n string to serve."""

    category: RefusalCategory
    message_key: str
    matched: str


# Each entry: (category, i18n key, pattern). Patterns are matched
# case-insensitively against the whole question.
_RULES: tuple[tuple[RefusalCategory, str, re.Pattern[str]], ...] = (
    # -- eligibility: never decided here (N3) -------------------------------
    (
        RefusalCategory.ELIGIBILITY,
        "agent.refuse_eligibility",
        re.compile(r"\b(in)?eligib\w*\b", re.I),
    ),
    (
        RefusalCategory.ELIGIBILITY,
        "agent.refuse_eligibility",
        re.compile(r"\bam i (allowed|able|qualified|permitted|registered)\b", re.I),
    ),
    (
        RefusalCategory.ELIGIBILITY,
        "agent.refuse_eligibility",
        re.compile(r"\bdo i qualify\b", re.I),
    ),
    (
        RefusalCategory.ELIGIBILITY,
        "agent.refuse_eligibility",
        re.compile(r"\b(felony|felon|convicted|conviction|parole|probation|incarcerated)\b", re.I),
    ),
    (
        RefusalCategory.ELIGIBILITY,
        "agent.refuse_eligibility",
        re.compile(
            r"\b(citizenship|non-?citizen|undocumented|green card|immigration status)\b", re.I
        ),
    ),
    (
        RefusalCategory.ELIGIBILITY,
        "agent.refuse_eligibility",
        re.compile(
            r"\b(can|could|may|will|would) (i|he|she|they|we) .{0,40}"
            r"\b(vote|register|be turned away|be denied)\b.{0,60}"
            r"\b(if|with|without|because|since|even though)\b",
            re.I,
        ),
    ),
    (
        RefusalCategory.ELIGIBILITY,
        "agent.refuse_eligibility",
        # "Is my tribal ID valid?", "Will their P.O. box address be accepted?"
        # — a judgement about one person's document, which is the election
        # office's call, not this device's (PRD §19 steward copy).
        re.compile(
            r"\b(is|are|will|would|does|do)\s+(my|his|her|their|this|that)\b"
            r"[\w\s.'-]{0,30}?"
            r"\b(id|ids|i\.d\.|identification|licen[cs]e|card|address|registration|document)s?\b"
            r"[\w\s]{0,30}?"
            r"\b(valid|accepted|acceptable|count|counts|enough|sufficient|ok|okay|good|work|"
            r"allowed|qualify)\b",
            re.I,
        ),
    ),
    (
        RefusalCategory.ELIGIBILITY,
        "agent.refuse_eligibility",
        re.compile(r"\b(purged|removed) from the (rolls|voter list|registration)\b", re.I),
    ),
    # -- partisan advice (§6.3 system prompt) -------------------------------
    (
        RefusalCategory.PARTISAN,
        "agent.refuse_partisan",
        re.compile(r"\bendors\w*\b", re.I),
    ),
    (
        RefusalCategory.PARTISAN,
        "agent.refuse_partisan",
        re.compile(r"\bwho (should|shall) (i|we) (vote for|support|pick|choose)\b", re.I),
    ),
    (
        RefusalCategory.PARTISAN,
        "agent.refuse_partisan",
        re.compile(r"\bwho (do|would) you (vote for|support|recommend|prefer)\b", re.I),
    ),
    (
        RefusalCategory.PARTISAN,
        "agent.refuse_partisan",
        re.compile(r"\b(best|better|worst|right|wrong) (candidate|party|choice)\b", re.I),
    ),
    (
        RefusalCategory.PARTISAN,
        "agent.refuse_partisan",
        re.compile(r"\bwhich (candidate|party) (is|will|would|should)\b", re.I),
    ),
    (
        RefusalCategory.PARTISAN,
        "agent.refuse_partisan",
        re.compile(r"\bwho (is|will be) (winning|going to win)\b", re.I),
    ),
    # -- prompt injection / "answer without files" --------------------------
    (
        RefusalCategory.INJECTION,
        "agent.refuse_injection",
        re.compile(
            r"\b(ignore|disregard|forget|bypass|override)\b.{0,40}"
            r"\b(file|files|document|documents|instruction|instructions|official|rule|rules|"
            r"citation|citations|prompt)\b",
            re.I,
        ),
    ),
    (
        RefusalCategory.INJECTION,
        "agent.refuse_injection",
        re.compile(r"\b(you are now|act as if|pretend (you|that|to be)|developer mode)\b", re.I),
    ),
    (
        RefusalCategory.INJECTION,
        "agent.refuse_injection",
        re.compile(r"\b(new|updated|real) (instructions?|system prompt)\b", re.I),
    ),
    (
        RefusalCategory.INJECTION,
        "agent.refuse_injection",
        re.compile(r"\bregardless of (the |what )?(files|documents|excerpts|sources)\b", re.I),
    ),
    (
        RefusalCategory.INJECTION,
        "agent.refuse_injection",
        re.compile(r"\bwithout (a |any )?citations?\b", re.I),
    ),
    (
        RefusalCategory.INJECTION,
        "agent.refuse_injection",
        re.compile(r"\b(make (it|something) up|just guess|guess the|invent|fabricate)\b", re.I),
    ),
    (
        RefusalCategory.INJECTION,
        "agent.refuse_injection",
        re.compile(
            r"\b(say|tell me|claim|state|pretend|answer)\b.{0,30}\bthat\b.{0,40}"
            r"\b(polls?|voting|vote|site|office)\b",
            re.I,
        ),
    ),
    # -- ballot secrecy (N5) -------------------------------------------------
    (
        RefusalCategory.BALLOT_SECRECY,
        "agent.refuse_ballot_secrecy",
        re.compile(r"\bwho did (i|he|she|they|you|we) vote for\b", re.I),
    ),
    (
        RefusalCategory.BALLOT_SECRECY,
        "agent.refuse_ballot_secrecy",
        re.compile(r"\b(prove|proof|receipt|show).{0,30}\b(i|they|he|she) voted\b", re.I),
    ),
    (
        RefusalCategory.BALLOT_SECRECY,
        "agent.refuse_ballot_secrecy",
        re.compile(r"\bhow did \w+ vote\b", re.I),
    ),
    # -- tallying or casting (N1, N2) ---------------------------------------
    (
        RefusalCategory.TALLY_OR_CASTING,
        "agent.refuse_tally",
        re.compile(r"\b(count|tally|total|add up)\b.{0,30}\b(votes?|ballots?)\b", re.I),
    ),
    (
        RefusalCategory.TALLY_OR_CASTING,
        "agent.refuse_tally",
        re.compile(
            r"\b(vote|cast (my |a )?ballot|submit (my )?ballot)\b.{0,20}"
            r"\b(online|by phone|by app|by text|by sms|here|on this|through this|remotely)\b",
            re.I,
        ),
    ),
    (
        RefusalCategory.TALLY_OR_CASTING,
        "agent.refuse_tally",
        re.compile(r"\b(results|totals) (so far|for|of) (the )?(election|race|precinct)\b", re.I),
    ),
)


def check(question: str) -> Refusal | None:
    """Return the first :class:`Refusal` that applies, or ``None`` to continue."""
    text = " ".join(question.split())
    for category, key, pattern in _RULES:
        match = pattern.search(text)
        if match:
            return Refusal(category=category, message_key=key, matched=match.group(0))
    return None
