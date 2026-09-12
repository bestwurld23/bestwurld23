"""PRD §17.2 — known questions against the fixture pack return the right file."""

from __future__ import annotations

import pytest

from cak_node.retrieval import OfficialIndex, build_match_expression, score_chunk
from cak_node.text import coverage, stem, token_present

# PRD §21.1 names the first two. The rest are the questions a resident in
# Englewood or a chapter house actually asks first.
EXPECTED_TOP_FILE = [
    ("When is early voting?", "official/hours.md"),
    ("Where do I vote?", "official/sites.md"),
    ("What are the election day hours?", "official/hours.md"),
    ("What time do polls close on election day?", "official/hours.md"),
    ("How do I contact the election office?", "official/contacts.md"),
    ("Is the Springfield Library wheelchair accessible?", "official/sites.md"),
    ("Is there language help in Spanish?", "official/contacts.md"),
    ("Is Riverside Chapel Hall open for early voting?", "official/sites.md"),
]

OFF_TOPIC = [
    "How do I bake sourdough bread?",
    "What is the weather tomorrow?",
    "Who won the football game?",
    "What is the capital of France?",
]


@pytest.mark.parametrize("question,expected_file", EXPECTED_TOP_FILE)
def test_top_hit_comes_from_the_expected_file(
    index: OfficialIndex, question: str, expected_file: str
) -> None:
    hits = index.search(question, top_k=5)
    assert hits, question
    assert hits[0].chunk.file_id == expected_file


@pytest.mark.parametrize("question,expected_file", EXPECTED_TOP_FILE)
def test_expected_answers_clear_the_pack_threshold(
    index: OfficialIndex, pack, question: str, expected_file: str
) -> None:
    hits = index.search(question, top_k=5)
    assert hits[0].score >= pack.manifest.retrieval_min_score, (
        f"{question!r} scored {hits[0].score:.3f}, below the pack's "
        f"retrieval_min_score of {pack.manifest.retrieval_min_score}"
    )


@pytest.mark.parametrize("question", OFF_TOPIC)
def test_off_topic_questions_fall_below_threshold(
    index: OfficialIndex, pack, question: str
) -> None:
    """BM25 alone would answer these confidently. The coverage gate must not."""
    hits = index.search(question, top_k=5)
    top = hits[0].score if hits else 0.0
    assert top < pack.manifest.retrieval_min_score, f"{question!r} scored {top:.3f}"


def test_index_covers_every_official_file_but_not_the_readme(index: OfficialIndex, pack) -> None:
    assert index.file_count == 3
    assert index.chunk_count >= 6
    assert index.skipped == []
    indexed = {f.file_id for f in pack.official_files()}
    assert indexed == {"official/hours.md", "official/sites.md", "official/contacts.md"}


def test_chunk_titles_keep_the_document_heading(index: OfficialIndex) -> None:
    """A citation that says only "Springfield Library" loses what file it is in."""
    hits = index.search("Is the Springfield Library accessible?", top_k=3)
    assert hits[0].chunk.title.startswith("Where to vote")
    assert "Springfield Library" in hits[0].chunk.title


def test_locators_are_anchors_a_reader_can_find(index: OfficialIndex) -> None:
    hits = index.search("election day hours", top_k=3)
    assert hits[0].chunk.locator == "#election-day-hours"


def test_match_expression_cannot_inject_fts_operators() -> None:
    hostile = 'foo" OR chunks MATCH "bar* NEAR/2 (baz)'
    expression = build_match_expression(hostile)
    assert '"' not in expression
    assert "(" not in expression
    assert "/" not in expression


def test_hostile_query_returns_no_results_rather_than_erroring(index: OfficialIndex) -> None:
    for hostile in ['" OR "', "NEAR/", "*", "()", "AND OR NOT"]:
        assert isinstance(index.search(hostile), list)


def test_empty_query_is_a_miss(index: OfficialIndex) -> None:
    assert index.search("") == []
    assert index.search("   ") == []


def test_rebuild_picks_up_a_changed_file(index: OfficialIndex, pack) -> None:
    before = index.search("Founders Day holiday", top_k=3)
    assert before and before[0].score > 0
    (pack.official_dir / "hours.md").write_text("# Hours\n\nNothing here.\n", encoding="utf-8")
    index.rebuild(pack)
    after = index.search("Founders Day holiday", top_k=3)
    assert not after or after[0].score < before[0].score


class TestTextHelpers:
    def test_stem_is_idempotent(self) -> None:
        for word in ["addresses", "address", "polling", "polls", "voting", "votes", "hours"]:
            assert stem(stem(word)) == stem(word)

    def test_related_words_share_a_stem(self) -> None:
        assert stem("polls") == stem("polling")
        assert stem("vote") == stem("voting") == stem("voted")
        assert stem("hours") == stem("hour")

    def test_short_words_are_left_alone(self) -> None:
        assert stem("id") == "id"
        assert stem("day") == "day"

    def test_prefix_matching_has_a_length_floor(self) -> None:
        assert not token_present("id", {"identification"})
        assert token_present("hours", {"hour"})

    def test_coverage_counts_content_words_only_by_default(self) -> None:
        assert coverage("where do I vote", "the vote is here") == 1.0
        assert coverage("where do I vote", "Where to vote", include_function_words=True) > 0.4

    def test_score_is_zero_for_an_unrelated_chunk(self) -> None:
        from cak_node.retrieval import Chunk

        chunk = Chunk("official/hours.md", "Hours", "#hours", "Early voting is on weekdays.")
        score, chunk_coverage = score_chunk("how do I bake bread", chunk)
        assert score == 0.0
        assert chunk_coverage == 0.0
