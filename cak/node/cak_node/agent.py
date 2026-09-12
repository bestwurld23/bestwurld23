"""The Civic Agent: a clerk that reads the steward's files out loud.

Normative source: PRD §6.3. The pipeline is, in order:

1. Scope guard (never answer an eligibility, partisan, secrecy or tally question)
2. BM25 retrieval over ``official/`` only
3. Threshold check against the pack's ``retrieval_min_score``
4. Generation strictly from the retrieved excerpts
5. Citation lock — fail closed if the answer outruns the excerpts
6. Attach citations and the election office contact

Every exit that is not a cited answer is the same exit: "I don't have that in
the official files on this device", plus the phone number of someone who does.
That is the P7 rule — fail open to humans.
"""

from __future__ import annotations

from dataclasses import dataclass

from cak_node import grounding, guard
from cak_node.i18n import Catalogue
from cak_node.llm import Generator, best_excerpt
from cak_node.models import AgentMeta, AgentResponse, Citation, Office
from cak_node.pack import LocalePack, OfficialFile
from cak_node.retrieval import Hit, OfficialIndex

DEFAULT_TOP_K = 6


@dataclass
class AgentConfig:
    top_k: int = DEFAULT_TOP_K
    max_citations: int = 3


class CivicAgent:
    """Stateless question answering over one loaded pack."""

    def __init__(
        self,
        pack: LocalePack,
        index: OfficialIndex,
        catalogue: Catalogue,
        generator: Generator,
        config: AgentConfig | None = None,
    ) -> None:
        self.pack = pack
        self.index = index
        self.catalogue = catalogue
        self.generator = generator
        self.config = config or AgentConfig()
        self._files: dict[str, OfficialFile] = {}
        self.refresh_file_metadata()

    def refresh_file_metadata(self) -> None:
        """Re-read provenance sidecars and hashes. Call after a steward write."""
        self._files = {f.file_id: f for f in self.pack.official_files()}

    # -- public API ----------------------------------------------------------
    def answer(self, question: str, language: str | None = None) -> AgentResponse:
        lang = self.catalogue.resolve_language(language)
        manifest = self.pack.manifest

        refusal = guard.check(question)
        if refusal is not None:
            return self._dont_know(
                lang,
                message=self.catalogue.get(refusal.message_key, lang, **self._office_fmt()),
                refusal_category=refusal.category.value,
            )

        hits = self.index.search(question, top_k=self.config.top_k)
        max_score = hits[0].score if hits else 0.0
        if not hits or max_score < manifest.retrieval_min_score:
            return self._dont_know(lang, retrieval_max_score=max_score)

        usable = [h for h in hits if h.score >= manifest.retrieval_min_score]
        answer_markdown = self.generator.generate(question, usable, lang)
        if not answer_markdown.strip():
            return self._dont_know(lang, retrieval_max_score=max_score)

        check = grounding.verify(
            answer_markdown,
            [h.chunk for h in usable],
            extra_allowed_text=self._framing_vocabulary(usable),
            allowed_numbers_text=self._official_contact_text(),
        )
        if not check.ok:
            # The model said something the files do not. Serve nothing.
            return self._dont_know(
                lang,
                retrieval_max_score=max_score,
                grounding_failure=check.reason,
            )

        citations = self._citations(question, usable)
        return AgentResponse(
            status="ok",
            language=lang,
            answer_markdown=answer_markdown,
            citations=citations,
            office=self._office(),
            disclaimer=self._disclaimer(lang),
            meta=AgentMeta(
                locale_id=manifest.locale_id,
                pack_version=manifest.pack_version,
                retrieval_max_score=round(max_score, 4),
                retrieval_min_score=manifest.retrieval_min_score,
                files_used=sorted({c.file_id for c in citations}),
                generator=self.generator.name,
            ),
        )

    # -- helpers -------------------------------------------------------------
    def _citations(self, question: str, hits: list[Hit]) -> list[Citation]:
        citations: list[Citation] = []
        seen: set[tuple[str, str]] = set()
        for hit in hits:
            key = (hit.chunk.file_id, hit.chunk.locator)
            if key in seen:
                continue
            seen.add(key)
            file = self._files.get(hit.chunk.file_id)
            citations.append(
                Citation(
                    file_id=hit.chunk.file_id,
                    title=hit.chunk.title,
                    locator=hit.chunk.locator,
                    excerpt=best_excerpt(hit.chunk.text, question),
                    sha256=file.sha256 if file else None,
                    source_url=file.source_url if file else None,
                )
            )
            if len(citations) >= self.config.max_citations:
                break
        return citations

    def _dont_know(
        self,
        language: str,
        message: str | None = None,
        refusal_category: str | None = None,
        retrieval_max_score: float = 0.0,
        grounding_failure: str | None = None,
    ) -> AgentResponse:
        manifest = self.pack.manifest
        text = message or self.catalogue.get("agent.dont_know", language, **self._office_fmt())
        return AgentResponse(
            status="i_dont_know",
            language=language,
            answer_markdown=text,
            citations=[],
            office=self._office(),
            disclaimer=self._disclaimer(language),
            meta=AgentMeta(
                locale_id=manifest.locale_id,
                pack_version=manifest.pack_version,
                retrieval_max_score=round(retrieval_max_score, 4),
                retrieval_min_score=manifest.retrieval_min_score,
                files_used=[],
                refusal_category=refusal_category,
                generator=self.generator.name,
                grounding_failure=grounding_failure,
            ),
        )

    def _office(self) -> Office:
        a = self.pack.manifest.authority
        return Office(name=a.name, phone=a.phone, address=a.address, url=a.url)

    def _office_fmt(self) -> dict[str, str]:
        a = self.pack.manifest.authority
        return {
            "authority": a.name,
            "phone": a.phone or "",
            "address": a.address or "",
            "url": a.url or "",
        }

    def _disclaimer(self, language: str) -> str:
        banner = self.catalogue.get("banner.not_an_election_office", language)
        if banner == "banner.not_an_election_office":
            return self.pack.manifest.legal_banner
        return banner

    def _framing_vocabulary(self, hits: list[Hit]) -> str:
        """Words the node itself may use: file titles, locators, the authority."""
        parts = [self.pack.manifest.authority.name, self.pack.manifest.name]
        parts += [f"{h.chunk.title} {h.chunk.locator} {h.chunk.file_id}" for h in hits]
        parts += list(self._files)
        return " ".join(parts)

    def _official_contact_text(self) -> str:
        """The only numbers allowed beyond the excerpts: the pack's own contact."""
        a = self.pack.manifest.authority
        return " ".join(filter(None, [a.phone, a.address, a.url]))
