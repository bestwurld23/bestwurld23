"""Paper Pack generation — the printable twin of every digital flow.

Normative source: PRD §9 (Paper Pack is a first-class product) and §3 P3.

The HTML render has no dependency beyond Jinja2, so a node can always produce
something a steward can print from a browser. PDF rendering additionally needs
WeasyPrint (the ``pdf`` extra); when it is absent the caller is told exactly
that rather than being handed a broken file.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from cak_node.i18n import Catalogue
from cak_node.pack import LocalePack

# Page sizes a cheap copier can actually handle (PRD §11.1: Letter + A4 + A5).
PAGE_SIZES: dict[str, str] = {
    "a5": "A5",
    "a4": "A4",
    "letter": "Letter",
    "5x7": "5in 7in",
}

DEFAULT_TEMPLATE_DIRS: tuple[Path, ...] = (
    # Running from a checkout: cak/node/cak_node/printing.py -> cak/print/templates
    Path(__file__).resolve().parents[2] / "print" / "templates",
    Path("/usr/share/cak/print/templates"),
)

# Last-resort template so /print never 500s on a node with a broken install.
_FALLBACK_TEMPLATE = """<!doctype html>
<html lang="{{ language }}"><head><meta charset="utf-8">
<title>{{ t('print.howto_title') }}</title></head><body>
<h1>{{ t('print.howto_title') }}</h1><p>{{ pack.name }}</p>
<p><strong>{{ pack.authority.name }}</strong><br>{{ pack.authority.phone or '' }}<br>
{{ pack.authority.address or '' }}</p>
<p>{{ pack.legal_banner }}</p></body></html>"""


class PdfUnavailable(RuntimeError):
    """Raised when a PDF is requested but WeasyPrint is not installed."""


class PaperPack:
    """Renders the pack's print artifacts."""

    def __init__(
        self, pack: LocalePack, catalogue: Catalogue, template_dir: Path | None = None
    ) -> None:
        self.pack = pack
        self.catalogue = catalogue
        self.template_dir = template_dir or _find_template_dir()
        if self.template_dir is not None:
            self.env = Environment(
                loader=FileSystemLoader(str(self.template_dir)),
                autoescape=select_autoescape(["html", "xml", "j2"]),
            )
        else:
            self.env = Environment(autoescape=select_autoescape(["html", "xml"]))

    # -- HTML ----------------------------------------------------------------
    def howto_html(self, language: str | None = None, page: str = "a5") -> str:
        lang = self.catalogue.resolve_language(language)
        context = self._context(lang, page)
        if self.template_dir is not None:
            template = self.env.get_template("howto.html.j2")
        else:
            template = self.env.from_string(_FALLBACK_TEMPLATE)
        return template.render(**context)

    # -- PDF -----------------------------------------------------------------
    def howto_pdf(self, language: str | None = None, page: str = "a5") -> bytes:
        html = self.howto_html(language=language, page=page)
        return html_to_pdf(html)

    # -- context -------------------------------------------------------------
    def _context(self, language: str, page: str) -> dict[str, Any]:
        manifest = self.pack.manifest
        features = self.pack.sites().get("features", [])
        sites = [f.get("properties", {}) for f in features]
        return {
            "language": language,
            "page_size": PAGE_SIZES.get(page.lower(), PAGE_SIZES["a5"]),
            "pack": {
                "name": manifest.name,
                "locale_id": manifest.locale_id,
                "pack_version": manifest.pack_version,
                "legal_banner": manifest.legal_banner,
                "authority": {
                    "name": manifest.authority.name,
                    "phone": manifest.authority.phone,
                    "address": manifest.authority.address,
                    "url": manifest.authority.url,
                },
            },
            "sites": sites,
            "sms_enabled": manifest.sms.enabled,
            "sms": {
                "wait_code": manifest.sms.wait_code,
                "closed_code": manifest.sms.closed_code,
                "help_code": manifest.sms.help_code,
            },
            "generated_at": datetime.now(UTC).strftime("%Y-%m-%d"),
            "t": lambda key, **fmt: self.catalogue.get(key, language, **fmt),
        }


def html_to_pdf(html: str) -> bytes:
    try:
        from weasyprint import HTML  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise PdfUnavailable(
            "PDF rendering needs WeasyPrint: pip install 'civic-access-kit[pdf]'. "
            "The printable HTML at /print/howto.html works without it."
        ) from exc
    return bytes(HTML(string=html).write_pdf())


def _find_template_dir() -> Path | None:
    for candidate in DEFAULT_TEMPLATE_DIRS:
        if (candidate / "howto.html.j2").is_file():
            return candidate
    return None
