"""PRD §17.9 — 10 concurrent local queries on Pi-class hardware.

The PRD asks for latency to be documented and explicitly rules out SLA theatre,
so this test asserts only what matters for correctness under concurrency —
every query is answered, and answered the same way — and records the observed
latency as test properties for whoever is reading the CI log.

Real Pi 5 numbers belong in docs/hardware.md, measured on the device. A CI
runner's timings say nothing about a Raspberry Pi, so nothing here fails on a
clock.
"""

from __future__ import annotations

import statistics
import time
from concurrent.futures import ThreadPoolExecutor

from cak_node.service import NodeService

QUESTIONS = [
    "When is early voting?",
    "Where do I vote?",
    "What are the election day hours?",
    "How do I contact the election office?",
    "Is the Springfield Library accessible?",
    "Is there language help in Spanish?",
    "When do polls close?",
    "Who should I vote for?",
    "Am I eligible if I have a felony?",
    "How do I bake sourdough bread?",
]


def test_ten_concurrent_queries_all_answer(service: NodeService, record_property) -> None:
    def ask(question: str) -> tuple[str, str, float]:
        started = time.perf_counter()
        response = service.answer(question)
        return question, response.status, time.perf_counter() - started

    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(ask, QUESTIONS))

    assert len(results) == len(QUESTIONS)
    for question, status, _ in results:
        assert status in {"ok", "i_dont_know"}, question

    latencies = sorted(elapsed for _, _, elapsed in results)
    record_property("concurrency", 10)
    record_property("latency_median_s", round(statistics.median(latencies), 4))
    record_property("latency_p90_s", round(latencies[int(len(latencies) * 0.9) - 1], 4))
    record_property("latency_max_s", round(latencies[-1], 4))


def test_concurrent_answers_match_serial_answers(service: NodeService) -> None:
    """A shared FTS connection must not hand one resident another's answer."""
    serial = {q: service.answer(q).answer_markdown for q in QUESTIONS}

    with ThreadPoolExecutor(max_workers=10) as pool:
        concurrent = dict(
            zip(
                QUESTIONS,
                pool.map(lambda q: service.answer(q).answer_markdown, QUESTIONS),
                strict=True,
            )
        )

    assert concurrent == serial


def test_repeated_queries_are_stable(service: NodeService) -> None:
    first = service.answer("When is early voting?")
    for _ in range(20):
        again = service.answer("When is early voting?")
        assert again.answer_markdown == first.answer_markdown
        assert [c.file_id for c in again.citations] == [c.file_id for c in first.citations]


def test_query_counters_survive_concurrency(service: NodeService) -> None:
    with ThreadPoolExecutor(max_workers=10) as pool:
        list(pool.map(service.answer, QUESTIONS))
    assert service.metrics()["queries_total"] == len(QUESTIONS)
