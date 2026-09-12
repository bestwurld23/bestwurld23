"""UI and agent string catalogue loaded from the pack's ``i18n/`` directory.

Normative source: PRD §6.2 (UI strings externalized) and §17.8 (a missing key
falls back instead of crashing). Nothing here ever raises on a missing key: a
kiosk in a chapter house must not white-screen because a translator skipped a
line.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class Catalogue:
    """Nested-key string lookup with a language fallback chain."""

    def __init__(self, tables: dict[str, dict[str, Any]], default_language: str) -> None:
        self._tables = tables
        self._default = default_language

    @classmethod
    def from_dir(cls, i18n_dir: Path, languages: list[str], default_language: str) -> Catalogue:
        tables: dict[str, dict[str, Any]] = {}
        for lang in languages:
            path = Path(i18n_dir) / f"{lang}.yaml"
            if not path.is_file():
                tables[lang] = {}
                continue
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
            tables[lang] = loaded if isinstance(loaded, dict) else {}
        return cls(tables, default_language)

    @property
    def languages(self) -> list[str]:
        return list(self._tables)

    def resolve_language(self, requested: str | None) -> str:
        """Pick the language actually served for ``requested``."""
        if requested and requested in self._tables:
            return requested
        if requested and "-" in requested:
            base = requested.split("-", 1)[0]
            if base in self._tables:
                return base
        return self._default

    def get(self, key: str, language: str | None = None, **fmt: object) -> str:
        """Look up ``key`` (e.g. ``agent.dont_know``), falling back safely.

        Order: requested language, then default language, then the key itself.
        Formatting failures degrade to the unformatted template rather than
        raising.
        """
        lang = self.resolve_language(language)
        for candidate in (lang, self._default):
            value = self._lookup(self._tables.get(candidate, {}), key)
            if isinstance(value, str):
                return _safe_format(value, fmt)
        return key

    @staticmethod
    def _lookup(table: dict[str, Any], key: str) -> Any:
        node: Any = table
        for part in key.split("."):
            if not isinstance(node, dict) or part not in node:
                return None
            node = node[part]
        return node


def _safe_format(template: str, fmt: dict[str, object]) -> str:
    if not fmt:
        return template
    try:
        return template.format(**fmt)
    except (KeyError, IndexError, ValueError):
        return template
