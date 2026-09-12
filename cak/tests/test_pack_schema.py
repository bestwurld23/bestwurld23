"""PRD §17.5 — an invalid pack.yaml is rejected, with a reason a steward can act on."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from cak_node.pack import PackValidationError, load_manifest, load_pack

VALID = {
    "cak_pack_version": 1,
    "locale_id": "us-xx-springfield",
    "name": "Springfield",
    "authority": {"name": "Springfield Civic Board", "phone": "555-0100"},
    "languages": ["en", "es"],
    "default_language": "en",
    "retrieval_min_score": 0.35,
    "legal_banner": "This is not an official election office.",
    "pack_version": "2026.09.12",
    "does_not": ["determine_eligibility", "collect_ballots"],
}


def write(tmp_path: Path, manifest: dict) -> Path:
    path = tmp_path / "pack.yaml"
    path.write_text(yaml.safe_dump(manifest), encoding="utf-8")
    return path


def test_valid_manifest_loads(tmp_path: Path) -> None:
    manifest = load_manifest(write(tmp_path, VALID))
    assert manifest.locale_id == "us-xx-springfield"
    assert manifest.official_dir == "official/"


@pytest.mark.parametrize(
    "mutation,expected_text",
    [
        ({"cak_pack_version": 2}, "cak_pack_version"),
        ({"locale_id": "Chicago Illinois"}, "locale_id"),
        ({"default_language": "fr"}, "default_language"),
        ({"retrieval_min_score": 1.7}, "retrieval_min_score"),
        ({"languages": []}, "languages"),
        ({"legal_banner": ""}, "legal_banner"),
        ({"does_not": ["collect_ballots"]}, "determine_eligibility"),
        ({"does_not": []}, "does_not"),
        ({"authority": {"phone": "555-0100"}}, "authority"),
    ],
)
def test_invalid_manifests_are_rejected(tmp_path: Path, mutation: dict, expected_text: str) -> None:
    manifest = {**VALID, **mutation}
    with pytest.raises(PackValidationError) as excinfo:
        load_manifest(write(tmp_path, manifest))
    assert expected_text in str(excinfo.value)


def test_unknown_keys_are_rejected(tmp_path: Path) -> None:
    """A typo'd key must not be silently ignored: it would look configured."""
    manifest = {**VALID, "retrival_min_score": 0.9}
    with pytest.raises(PackValidationError):
        load_manifest(write(tmp_path, manifest))


def test_a_pack_claiming_to_determine_eligibility_is_refused(tmp_path: Path) -> None:
    """PRD §2.2 N3 is enforced by the loader, not just by documentation."""
    manifest = {**VALID, "does_not": ["collect_ballots", "tally_votes"]}
    with pytest.raises(PackValidationError) as excinfo:
        load_manifest(write(tmp_path, manifest))
    assert "determine_eligibility" in str(excinfo.value)


def test_missing_manifest(tmp_path: Path) -> None:
    with pytest.raises(PackValidationError) as excinfo:
        load_pack(tmp_path)
    assert "pack.yaml" in str(excinfo.value)


def test_malformed_yaml(tmp_path: Path) -> None:
    (tmp_path / "pack.yaml").write_text("cak_pack_version: [1\n", encoding="utf-8")
    with pytest.raises(PackValidationError) as excinfo:
        load_manifest(tmp_path / "pack.yaml")
    assert "valid YAML" in str(excinfo.value)


def test_missing_official_dir_is_rejected(tmp_path: Path, pack_dir: Path) -> None:
    import shutil

    broken = tmp_path / "broken"
    shutil.copytree(pack_dir, broken)
    shutil.rmtree(broken / "official")
    with pytest.raises(PackValidationError) as excinfo:
        load_pack(broken)
    assert "official" in str(excinfo.value)


def test_missing_sites_file_is_rejected(tmp_path: Path, pack_dir: Path) -> None:
    import shutil

    broken = tmp_path / "broken"
    shutil.copytree(pack_dir, broken)
    (broken / "sites" / "sites.geojson").unlink()
    with pytest.raises(PackValidationError) as excinfo:
        load_pack(broken)
    assert "sites" in str(excinfo.value)


def test_fixture_pack_is_valid(pack) -> None:
    assert pack.manifest.locale_id == "us-xx-springfield"
    assert pack.manifest.languages == ["en", "es"]
    assert len(pack.official_files()) == 3
    assert pack.sites()["type"] == "FeatureCollection"
    assert len(pack.sites()["features"]) == 3


def test_provenance_sidecars_are_loaded_and_match_the_files(pack) -> None:
    """PRD §10.4: each official file records where it came from."""
    from cak_node.hashing import sha256_file

    for file in pack.official_files():
        assert file.source_url, file.file_id
        assert file.retrieved_at, file.file_id
        assert file.authority == "Springfield Civic Board"
        assert file.sha256 == sha256_file(file.path)


def test_sidecar_hashes_in_the_repo_are_current(pack) -> None:
    """A stale sidecar hash is a provenance claim that no longer holds."""
    import yaml as yaml_module

    for file in pack.official_files():
        sidecar = file.path.with_name(file.path.name + ".meta.yaml")
        recorded = yaml_module.safe_load(sidecar.read_text(encoding="utf-8"))["sha256"]
        assert recorded == file.sha256, f"{sidecar} is stale"
