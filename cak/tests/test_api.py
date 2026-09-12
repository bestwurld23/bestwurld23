"""HTTP surface (PRD §11.4): public routes are open, steward routes are not."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from cak_node.config import ConfigError, NodeConfig, hash_password, verify_password


def test_health(client) -> None:
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["locale_id"] == "us-xx-springfield"
    assert body["official_file_count"] == 3
    assert body["generator"] == "extractive"
    assert body["offline"] is True
    assert body["disk_total_bytes"] > 0


def test_pack_exposes_files_and_hashes(client) -> None:
    body = client.get("/pack").json()
    assert body["locale_id"] == "us-xx-springfield"
    assert body["authority"]["name"] == "Springfield Civic Board"
    files = {f["file_id"]: f for f in body["official_files"]}
    assert set(files) == {"official/hours.md", "official/sites.md", "official/contacts.md"}
    assert all(len(f["sha256"]) == 64 for f in files.values())
    assert all(f["source_url"] for f in files.values())


def test_sites_is_geojson(client) -> None:
    body = client.get("/sites").json()
    assert body["type"] == "FeatureCollection"
    assert {f["properties"]["id"] for f in body["features"]} == {"site01", "site02", "site03"}


def test_files_served_with_their_hash(client) -> None:
    reply = client.get("/files/official/hours.md")
    assert reply.status_code == 200
    assert reply.headers["X-CAK-SHA256"]
    assert "Early voting" in reply.text


@pytest.mark.parametrize(
    "path",
    [
        "/files/official/../pack.yaml",
        "/files/../../etc/passwd",
        "/files/official/README.md",
        "/files/nope.md",
    ],
)
def test_only_indexed_official_files_are_servable(client, path: str) -> None:
    assert client.get(path).status_code == 404


def test_agent_query_response_shape(client) -> None:
    """PRD §11.3 is normative: these fields are the contract."""
    body = client.post("/agent/query", json={"text": "When is early voting?"}).json()
    assert set(body) >= {
        "status",
        "language",
        "answer_markdown",
        "citations",
        "office",
        "disclaimer",
    }
    assert body["status"] == "ok"
    citation = body["citations"][0]
    assert set(citation) >= {"file_id", "title", "locator", "excerpt"}
    assert body["office"]["phone"] == "555-0100"


def test_agent_query_rejects_empty_and_oversized(client) -> None:
    assert client.post("/agent/query", json={"text": ""}).status_code == 422
    assert client.post("/agent/query", json={"text": "x" * 2001}).status_code == 422
    assert client.post("/agent/query", json={"nope": 1}).status_code == 422


def test_agent_prompt_is_published(client) -> None:
    body = client.get("/agent/prompt").text
    assert "civic information clerk" in body
    assert "You do not decide who may vote" in body


def test_changelog_is_public(client) -> None:
    body = client.get("/changelog").json()
    assert body["chain_ok"] is True
    assert body["records"][0]["action"] == "genesis"
    assert body["problems"] == []


def test_changelog_verify_by_hash(client, service) -> None:
    from cak_changelog import hash_file

    digest = hash_file(service.pack.official_dir / "hours.md")
    found = client.get("/changelog/verify", params={"sha256": digest}).json()
    assert found["known"] is True
    assert found["records"]

    unknown = client.get("/changelog/verify", params={"sha256": "0" * 64}).json()
    assert unknown["known"] is False


def test_metrics_are_plain_counters(client) -> None:
    client.post("/agent/query", json={"text": "When is early voting?"})
    body = client.get("/metrics").text
    assert "cak_queries_total 1" in body
    assert "No personal data" in body


def test_print_html_always_renders(client) -> None:
    reply = client.get("/print/howto.html")
    assert reply.status_code == 200
    assert "Springfield Library" in reply.text
    assert "555-0100" in reply.text
    assert "not an official election office" in reply.text.lower()


def test_print_html_in_spanish(client) -> None:
    reply = client.get("/print/howto.html", params={"language": "es"})
    assert "Cómo votar" in reply.text
    assert "no es partidista" in reply.text.lower()


def test_print_pdf_either_renders_or_says_why(client) -> None:
    reply = client.get("/print/howto.pdf")
    if reply.status_code == 200:
        assert reply.content.startswith(b"%PDF")
    else:
        assert reply.status_code == 503
        assert "WeasyPrint" in reply.json()["detail"]


class TestKiosk:
    def test_get_renders_the_form_and_banner(self, client) -> None:
        page = client.get("/")
        assert page.status_code == 200
        assert 'name="q"' in page.text
        assert "not an official election office" in page.text.lower()

    def test_post_renders_an_answer_with_citations(self, client) -> None:
        page = client.post("/", data={"q": "When is early voting?"})
        assert page.status_code == 200
        assert "8am to 6pm" in page.text
        assert "official/hours.md" in page.text

    def test_post_renders_a_refusal(self, client) -> None:
        page = client.post("/", data={"q": "Who should I vote for?"})
        assert "555-0100" in page.text
        assert "candidates" in page.text.lower()

    def test_spanish_kiosk(self, client) -> None:
        page = client.post("/", data={"q": "¿Dónde voto?", "language": "es"})
        assert page.status_code == 200
        assert "Información para votar" in page.text


class TestStewardAuth:
    def test_steward_routes_require_auth(self, client) -> None:
        assert client.get("/steward/audit").status_code == 401
        assert client.post("/steward/load-folder", data={}).status_code == 401
        assert (
            client.post(
                "/steward/files", files={"file": ("a.md", io.BytesIO(b"# x"), "text/markdown")}
            ).status_code
            == 401
        )

    def test_wrong_password_is_refused(self, client) -> None:
        assert client.get("/steward/audit", auth=("steward", "wrong")).status_code == 401
        assert (
            client.get("/steward/audit", auth=("root", "correct-horse-battery")).status_code == 401
        )

    def test_correct_password_works(self, client, steward_auth) -> None:
        reply = client.get("/steward/audit", auth=steward_auth)
        assert reply.status_code == 200
        assert "entries" in reply.json()

    def test_upload_replaces_a_file_and_logs_it(self, client, steward_auth, service) -> None:
        seq = service.changelog.head().seq
        payload = b"# Early voting hours\n\nEarly voting runs on weekdays from 7am to 9pm.\n"
        reply = client.post(
            "/steward/files",
            auth=steward_auth,
            files={"file": ("hours.md", io.BytesIO(payload), "text/markdown")},
            data={"source": "Board download"},
        )
        assert reply.status_code == 200, reply.text
        assert reply.json()["accepted"] == ["hours.md"]
        assert service.changelog.head().seq == seq + 1

        answer = client.post("/agent/query", json={"text": "When is early voting?"}).json()
        assert "7am to 9pm" in answer["citations"][0]["excerpt"]

    def test_upload_of_a_forbidden_type_is_refused(self, client, steward_auth) -> None:
        reply = client.post(
            "/steward/files",
            auth=steward_auth,
            files={"file": ("voters.xlsx", io.BytesIO(b"PK\x03\x04"), "application/vnd.ms-excel")},
        )
        assert reply.status_code == 400
        assert "voters.xlsx" in str(reply.json()["rejected"])


class TestConfig:
    def test_password_round_trip(self) -> None:
        encoded = hash_password("hunter2", iterations=1_000)
        assert verify_password("hunter2", encoded)
        assert not verify_password("hunter3", encoded)
        assert not verify_password("", encoded)
        assert not verify_password("hunter2", None)
        assert "hunter2" not in encoded

    def test_lan_binding_requires_a_password(self, pack_dir: Path) -> None:
        with pytest.raises(ConfigError) as excinfo:
            NodeConfig(locale_pack=pack_dir, bind="0.0.0.0")
        assert "steward_password_hash" in str(excinfo.value)

    def test_localhost_binding_without_a_password_is_allowed(self, pack_dir: Path) -> None:
        config = NodeConfig(locale_pack=pack_dir)
        assert config.is_localhost_only

    def test_unsupported_backend_is_rejected(self, pack_dir: Path) -> None:
        with pytest.raises(ConfigError):
            NodeConfig(locale_pack=pack_dir, retrieval_backend="pinecone")

    def test_unknown_generator_is_rejected(self, pack_dir: Path) -> None:
        with pytest.raises(ConfigError):
            NodeConfig(locale_pack=pack_dir, generator="openai")

    def test_toml_round_trip(self, tmp_path: Path, pack_dir: Path) -> None:
        config_path = tmp_path / "node.toml"
        config_path.write_text(
            f'locale_pack = "{pack_dir}"\nport = 9090\nlog_queries = true\n', encoding="utf-8"
        )
        config = NodeConfig.from_toml(config_path)
        assert config.port == 9090
        assert config.log_queries is True
        assert config.locale_pack == pack_dir

    def test_relative_paths_resolve_next_to_the_config(
        self, tmp_path: Path, pack_dir: Path
    ) -> None:
        import shutil

        home = tmp_path / "deploy"
        home.mkdir()
        shutil.copytree(pack_dir, home / "pack")
        (home / "node.toml").write_text(
            'locale_pack = "pack"\ndb_path = "state/cak.db"\n', encoding="utf-8"
        )
        config = NodeConfig.from_toml(home / "node.toml")
        assert config.locale_pack == (home / "pack").resolve()
        assert config.db_path == (home / "state" / "cak.db").resolve()
