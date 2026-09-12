"""NodeService — the one object that owns a running node's state.

Keeping assembly here (rather than in the FastAPI module) means the whole node
can be driven from a test or a CLI without an HTTP server, which is what makes
the offline behaviour testable (PRD §17.4).
"""

from __future__ import annotations

import shutil
from pathlib import Path

from cak_changelog import Changelog, logged_file, open_log
from cak_node.agent import AgentConfig, CivicAgent
from cak_node.config import NodeConfig
from cak_node.i18n import Catalogue
from cak_node.llm import build_generator
from cak_node.models import (
    AgentResponse,
    HealthResponse,
    OfficialDirVerification,
    StewardLoadResult,
)
from cak_node.pack import LocalePack, load_pack
from cak_node.retrieval import OfficialIndex
from cak_node.steward import (
    StewardContext,
    load_from_folder,
    save_uploaded_file,
    verify_official_dir,
)
from cak_node.storage import Store

__version__ = "0.1.0"


class NodeService:
    """A loaded pack, an index, a log and a store — the whole appliance."""

    def __init__(self, config: NodeConfig) -> None:
        self.config = config
        self.pack: LocalePack = load_pack(config.locale_pack)
        self.index = OfficialIndex()
        self.index.rebuild(self.pack)
        self.catalogue = Catalogue.from_dir(
            self.pack.i18n_dir,
            self.pack.manifest.languages,
            self.pack.manifest.default_language,
        )
        self.generator = build_generator(config.generator, config.model, config.ollama_host)
        self.store = Store(config.db_path, log_queries=config.log_queries)
        self.changelog = self._open_changelog()
        self.agent = CivicAgent(
            pack=self.pack,
            index=self.index,
            catalogue=self.catalogue,
            generator=self.generator,
            config=AgentConfig(top_k=config.top_k),
        )

    # -- lifecycle -----------------------------------------------------------
    def _open_changelog(self) -> Changelog:
        """Open the log, creating the key and genesis record on first boot.

        A node whose log starts empty would report every official file as
        "never logged", so first boot records the pack it was shipped with.
        """
        log = open_log(self.config.changelog_path, self.config.changelog_key, create_key=True)
        if not log.exists():
            from cak_changelog import keys

            private = keys.load_private_key(self.config.changelog_key)
            log.genesis(
                log_id=self.config.log_id,
                locale_id=self.pack.manifest.locale_id,
                public_key_pem=keys.public_key_pem(private),
                note="Node first boot. Process files only; never ballots.",
            )
            files = [
                logged_file(f.path, f.file_id, source=f.source_url or "shipped with pack")
                for f in self.pack.official_files()
            ]
            if files:
                record = log.append(
                    action="pack_install",
                    files=files,
                    note=f"pack {self.pack.manifest.locale_id} {self.pack.manifest.pack_version}",
                    locale_id=self.pack.manifest.locale_id,
                )
                self.store.audit(
                    "pack_install",
                    detail=f"{len(files)} official files",
                    changelog_seq=record.seq,
                )
        return log

    def reload_pack(self) -> None:
        """Re-read the pack from disk and rebuild everything derived from it."""
        self.pack = load_pack(self.config.locale_pack)
        self.index.rebuild(self.pack)
        self.catalogue = Catalogue.from_dir(
            self.pack.i18n_dir,
            self.pack.manifest.languages,
            self.pack.manifest.default_language,
        )
        self.agent = CivicAgent(
            pack=self.pack,
            index=self.index,
            catalogue=self.catalogue,
            generator=self.generator,
            config=AgentConfig(top_k=self.config.top_k),
        )

    def close(self) -> None:
        self.index.close()
        self.store.close()

    # -- resident-facing -----------------------------------------------------
    def answer(self, text: str, language: str | None = None) -> AgentResponse:
        response = self.agent.answer(text, language)
        meta = response.meta
        self.store.record_query(
            text=text,
            language=response.language,
            status=response.status,
            refusal_category=meta.refusal_category if meta else None,
            max_score=meta.retrieval_max_score if meta else None,
            files_used=meta.files_used if meta else None,
        )
        return response

    # -- steward-facing ------------------------------------------------------
    def steward_context(self, actor_role: str = "steward") -> StewardContext:
        return StewardContext(pack=self.pack, changelog=self.changelog, actor_role=actor_role)

    def load_folder(
        self, source_dir: Path, source_note: str | None = None, dry_run: bool = False
    ) -> StewardLoadResult:
        """USB/folder load, then reindex so answers change immediately."""
        result = load_from_folder(
            Path(source_dir), self.steward_context(), source_note=source_note, dry_run=dry_run
        )
        if result.accepted and not dry_run:
            self.reload_pack()
            self.store.audit(
                "load_folder",
                detail=f"{len(result.accepted)} file(s) from {source_dir}",
                changelog_seq=result.changelog_seq,
            )
        result.indexed_chunk_count = self.index.chunk_count
        return result

    def load_upload(
        self, filename: str, data: bytes, source_note: str | None = None
    ) -> StewardLoadResult:
        result = save_uploaded_file(filename, data, self.steward_context(), source_note=source_note)
        if result.accepted:
            self.reload_pack()
            self.store.audit(
                "upload",
                detail=f"{filename} ({len(data)} bytes)",
                changelog_seq=result.changelog_seq,
            )
        result.indexed_chunk_count = self.index.chunk_count
        return result

    def verify_files(self) -> OfficialDirVerification:
        return verify_official_dir(self.pack, self.changelog)

    # -- introspection -------------------------------------------------------
    def health(self) -> HealthResponse:
        head = self.changelog.head()
        chain = self.changelog.verify()
        try:
            usage = shutil.disk_usage(self.pack.root)
            free, total = usage.free, usage.total
        except OSError:
            free = total = None
        degraded = bool(self.index.skipped) or not chain.ok or self.index.chunk_count == 0
        return HealthResponse(
            status="degraded" if degraded else "ok",
            version=__version__,
            locale_id=self.pack.manifest.locale_id,
            pack_version=self.pack.manifest.pack_version,
            official_file_count=self.index.file_count,
            indexed_chunk_count=self.index.chunk_count,
            index_skipped=self.index.skipped,
            generator=self.generator.name,
            model_loaded=self.generator.model_loaded,
            changelog_seq=head.seq if head else None,
            changelog_ok=chain.ok,
            disk_free_bytes=free,
            disk_total_bytes=total,
            offline=True,
        )

    def metrics(self) -> dict[str, int]:
        return self.store.counters()
