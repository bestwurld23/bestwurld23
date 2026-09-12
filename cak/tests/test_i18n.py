"""PRD §17.8 — a missing key falls back without crashing."""

from __future__ import annotations

from pathlib import Path

import yaml

from cak_node.i18n import Catalogue


def test_lookup_in_the_requested_language(catalogue: Catalogue) -> None:
    assert "no tengo esa información" in catalogue.get("agent.dont_know", "es").lower()
    assert "i don't have that" in catalogue.get("agent.dont_know", "en").lower()


def test_missing_key_returns_the_key_instead_of_raising(catalogue: Catalogue) -> None:
    assert catalogue.get("agent.does_not_exist", "en") == "agent.does_not_exist"
    assert catalogue.get("totally.made.up.path", "es") == "totally.made.up.path"


def test_missing_language_falls_back_to_the_default(catalogue: Catalogue) -> None:
    """A resident asking in an unshipped language gets English, not an error."""
    assert catalogue.get("agent.dont_know", "fr") == catalogue.get("agent.dont_know", "en")
    assert catalogue.resolve_language("fr") == "en"


def test_regional_variants_resolve_to_the_base_language(catalogue: Catalogue) -> None:
    assert catalogue.resolve_language("es-MX") == "es"
    assert catalogue.resolve_language("en-US") == "en"


def test_partial_translation_falls_back_per_key(tmp_path: Path) -> None:
    """A translator who finishes half the file must not break the other half."""
    (tmp_path / "en.yaml").write_text(
        yaml.safe_dump({"agent": {"dont_know": "I don't know", "extra": "English only"}}),
        encoding="utf-8",
    )
    (tmp_path / "nv.yaml").write_text(
        yaml.safe_dump({"agent": {"dont_know": "Doo shił bééhózin da"}}), encoding="utf-8"
    )
    catalogue = Catalogue.from_dir(tmp_path, ["en", "nv"], "en")
    assert catalogue.get("agent.dont_know", "nv") == "Doo shił bééhózin da"
    assert catalogue.get("agent.extra", "nv") == "English only"


def test_missing_language_file_is_not_fatal(tmp_path: Path) -> None:
    (tmp_path / "en.yaml").write_text(yaml.safe_dump({"a": {"b": "hello"}}), encoding="utf-8")
    catalogue = Catalogue.from_dir(tmp_path, ["en", "es"], "en")
    assert catalogue.get("a.b", "es") == "hello"


def test_empty_language_file_is_not_fatal(tmp_path: Path) -> None:
    (tmp_path / "en.yaml").write_text("", encoding="utf-8")
    catalogue = Catalogue.from_dir(tmp_path, ["en"], "en")
    assert catalogue.get("anything", "en") == "anything"


def test_formatting_placeholders_are_filled(catalogue: Catalogue) -> None:
    text = catalogue.get(
        "agent.dont_know",
        "en",
        authority="Springfield Civic Board",
        phone="555-0100",
        address="10 Civic Plaza",
    )
    assert "Springfield Civic Board" in text
    assert "555-0100" in text
    assert "{authority}" not in text


def test_a_missing_placeholder_degrades_instead_of_raising(catalogue: Catalogue) -> None:
    text = catalogue.get("agent.dont_know", "en")
    assert isinstance(text, str)
    assert text


def test_both_languages_answer_in_their_own_language(service) -> None:
    english = service.answer("Am I eligible if I have a felony?", "en")
    spanish = service.answer("Am I eligible if I have a felony?", "es")
    assert english.language == "en"
    assert spanish.language == "es"
    assert "oficina electoral" in spanish.answer_markdown.lower()
    assert "555-0100" in spanish.answer_markdown


def test_banner_is_translated(service) -> None:
    spanish = service.answer("Who should I vote for?", "es")
    assert "oficina electoral oficial" in spanish.disclaimer.lower()


def test_every_english_key_exists_in_spanish(pack) -> None:
    """A pack shipping two languages must not be half-translated (PRD §14)."""
    english = yaml.safe_load((pack.i18n_dir / "en.yaml").read_text(encoding="utf-8"))
    spanish = yaml.safe_load((pack.i18n_dir / "es.yaml").read_text(encoding="utf-8"))

    def flatten(table: dict, prefix: str = "") -> set[str]:
        out: set[str] = set()
        for key, value in table.items():
            path = f"{prefix}{key}"
            if isinstance(value, dict):
                out |= flatten(value, f"{path}.")
            else:
                out.add(path)
        return out

    missing = flatten(english) - flatten(spanish)
    assert not missing, f"untranslated keys in es.yaml: {sorted(missing)}"
