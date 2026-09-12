"""Shared fixtures.

Every test runs against a throwaway copy of ``packs/dev-fixture`` so tests can
replace official files, tamper with them on disk, and append to the change log
without touching the repository.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from cak_node.config import NodeConfig, hash_password
from cak_node.i18n import Catalogue
from cak_node.llm import ExtractiveGenerator
from cak_node.pack import load_pack
from cak_node.retrieval import OfficialIndex
from cak_node.service import NodeService

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PACK = REPO_ROOT / "packs" / "dev-fixture"

STEWARD_PASSWORD = "correct-horse-battery"


@pytest.fixture
def pack_dir(tmp_path: Path) -> Path:
    """A writable copy of the dev fixture pack."""
    destination = tmp_path / "pack"
    shutil.copytree(FIXTURE_PACK, destination)
    return destination


@pytest.fixture
def pack(pack_dir: Path):
    return load_pack(pack_dir)


@pytest.fixture
def index(pack) -> OfficialIndex:
    idx = OfficialIndex()
    idx.rebuild(pack)
    yield idx
    idx.close()


@pytest.fixture
def catalogue(pack) -> Catalogue:
    return Catalogue.from_dir(
        pack.i18n_dir, pack.manifest.languages, pack.manifest.default_language
    )


@pytest.fixture
def agent(pack, index, catalogue):
    from cak_node.agent import CivicAgent

    return CivicAgent(pack, index, catalogue, ExtractiveGenerator())


@pytest.fixture
def node_config(tmp_path: Path, pack_dir: Path) -> NodeConfig:
    return NodeConfig(
        locale_pack=pack_dir,
        bind="127.0.0.1",
        port=8080,
        steward_password_hash=hash_password(STEWARD_PASSWORD, iterations=1_000),
        db_path=tmp_path / "cak.db",
        changelog_path=tmp_path / "changelog.jsonl",
        changelog_key=tmp_path / "steward.ed25519",
        steward_inbox=tmp_path / "usb",
        log_id="caklog_test",
    )


@pytest.fixture
def service(node_config: NodeConfig) -> NodeService:
    node = NodeService(node_config)
    yield node
    node.close()


@pytest.fixture
def client(service: NodeService):
    from fastapi.testclient import TestClient

    from cak_node.app import create_app

    app = create_app(service.config, service=service)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def steward_auth() -> tuple[str, str]:
    return ("steward", STEWARD_PASSWORD)
