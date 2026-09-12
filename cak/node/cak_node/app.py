"""FastAPI application for the Civic Node (PRD §11.4).

Public routes are read-only. Steward routes require a local password and are
refused outright unless one is configured. Nothing here talks to the internet.
"""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from jinja2 import Environment, FileSystemLoader, select_autoescape

from cak_node.config import NodeConfig, verify_password
from cak_node.models import (
    AgentQuery,
    AgentResponse,
    HealthResponse,
    OfficialDirVerification,
    StewardLoadResult,
    VerifyFileResult,
)
from cak_node.printing import PaperPack, PdfUnavailable
from cak_node.service import NodeService, __version__

STEWARD_USERNAME = "steward"
WEB_DIR = Path(__file__).resolve().parent / "web"

security = HTTPBasic(auto_error=False)


def create_app(config: NodeConfig, service: NodeService | None = None) -> FastAPI:
    """Build the app around an already-loaded :class:`NodeService`."""
    app = FastAPI(
        title="Civic Access Kit — Civic Node",
        version=__version__,
        summary="Offline-first civic information. Not an election office, not a voting machine.",
        description=(
            "Answers are quoted from official files on this device and always carry "
            "citations. This node does not decide eligibility, does not handle ballots, "
            "and stores no personal data. See PRD §2.2."
        ),
    )
    app.state.config = config
    app.state.service = service or NodeService(config)
    app.state.jinja = Environment(
        loader=FileSystemLoader(str(WEB_DIR)),
        autoescape=select_autoescape(["html", "xml", "j2"]),
    )

    _register_routes(app)
    return app


def get_service(request: Request) -> NodeService:
    return request.app.state.service


ServiceDep = Annotated[NodeService, Depends(get_service)]


def require_steward(
    request: Request,
    credentials: Annotated[HTTPBasicCredentials | None, Depends(security)] = None,
) -> str:
    """Local password auth for steward routes (PRD §6.2, §11.4).

    A node with no ``steward_password_hash`` has no steward API at all. That is
    deliberate: an unconfigured node on a shared LAN must not be writable.
    """
    config: NodeConfig = request.app.state.config
    if not config.steward_password_hash:
        raise HTTPException(
            status_code=503,
            detail=(
                "Steward mode is disabled: no steward_password_hash in node.toml. "
                "Run 'cak-node hash-password' and add it, then restart."
            ),
        )
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Steward password required",
            headers={"WWW-Authenticate": "Basic realm=cak-steward"},
        )
    user_ok = secrets.compare_digest(credentials.username, STEWARD_USERNAME)
    password_ok = verify_password(credentials.password, config.steward_password_hash)
    if not (user_ok and password_ok):
        raise HTTPException(
            status_code=401,
            detail="Bad steward credentials",
            headers={"WWW-Authenticate": "Basic realm=cak-steward"},
        )
    return credentials.username


StewardDep = Annotated[str, Depends(require_steward)]


def _register_routes(app: FastAPI) -> None:  # noqa: C901 - a flat route table reads better
    # -- resident, read-only -------------------------------------------------
    @app.get("/health", response_model=HealthResponse, tags=["public"])
    def health(service: ServiceDep) -> HealthResponse:
        return service.health()

    @app.get("/pack", tags=["public"])
    def get_pack(service: ServiceDep) -> dict[str, Any]:
        """The manifest, so anyone can see which files and authority are loaded."""
        manifest = service.pack.manifest.model_dump()
        manifest["official_files"] = [
            {
                "file_id": f.file_id,
                "title": f.title,
                "media_type": f.media_type,
                "bytes": f.bytes,
                "sha256": f.sha256,
                "source_url": f.source_url,
                "retrieved_at": f.retrieved_at,
                "authority": f.authority,
            }
            for f in service.pack.official_files()
        ]
        return manifest

    @app.get("/sites", tags=["public"])
    def get_sites(service: ServiceDep) -> dict[str, Any]:
        return service.pack.sites()

    @app.get("/files/{file_id:path}", tags=["public"])
    def get_file(file_id: str, service: ServiceDep) -> Response:
        """Serve an official file verbatim. Only files the index knows about."""
        known = {f.file_id: f for f in service.pack.official_files()}
        file = known.get(file_id)
        if file is None:
            raise HTTPException(status_code=404, detail=f"no official file {file_id!r}")
        return Response(
            content=file.path.read_bytes(),
            media_type=file.media_type,
            headers={
                "X-CAK-SHA256": file.sha256,
                "Content-Disposition": f'inline; filename="{file.path.name}"',
            },
        )

    @app.post("/agent/query", response_model=AgentResponse, tags=["public"])
    def agent_query(query: AgentQuery, service: ServiceDep) -> AgentResponse:
        return service.answer(query.text, query.language)

    @app.get("/agent/prompt", response_class=PlainTextResponse, tags=["public"])
    def agent_prompt() -> str:
        """The agent's system prompt, verbatim. Auditors should not have to guess."""
        from cak_node.llm import SYSTEM_PROMPT

        return SYSTEM_PROMPT

    @app.get("/metrics", tags=["public"], response_class=PlainTextResponse)
    def metrics(service: ServiceDep) -> str:
        """Counters only, no personal data (PRD §11.4)."""
        lines = [
            "# Civic Access Kit counters. No personal data (PRD §13).",
            *(f"cak_{name} {value}" for name, value in sorted(service.metrics().items())),
        ]
        return "\n".join(lines) + "\n"

    # -- change log ----------------------------------------------------------
    @app.get("/changelog", tags=["changelog"])
    def get_changelog(service: ServiceDep, limit: int = Query(default=200, ge=1, le=5000)) -> dict:
        records = service.changelog.all_records()
        report = service.changelog.verify()
        return {
            "log_id": records[0].log_id if records else None,
            "chain_ok": report.ok,
            "problems": report.problems,
            "record_count": len(records),
            "records": [r.model_dump(by_alias=True, exclude_none=True) for r in records[-limit:]],
        }

    @app.get("/changelog/verify", response_model=VerifyFileResult, tags=["changelog"])
    def verify_hash(
        service: ServiceDep, sha256: str = Query(min_length=64, max_length=71)
    ) -> VerifyFileResult:
        """Paste a file hash, find out whether this node ever logged it (PRD §8.3)."""
        digest = sha256.removeprefix("sha256:").lower()
        records = service.changelog.find_by_sha256(digest)
        return VerifyFileResult(
            sha256=digest,
            known=bool(records),
            records=[r.model_dump(by_alias=True, exclude_none=True) for r in records],
        )

    @app.get("/changelog/verify-files", response_model=OfficialDirVerification, tags=["changelog"])
    def verify_files(service: ServiceDep) -> OfficialDirVerification:
        """Compare official/ on disk against the log. Detects out-of-band edits."""
        return service.verify_files()

    # -- steward -------------------------------------------------------------
    @app.post("/steward/files", response_model=StewardLoadResult, tags=["steward"])
    async def steward_upload(
        service: ServiceDep,
        _actor: StewardDep,
        file: UploadFile,
        source: Annotated[str | None, Form()] = None,
    ) -> StewardLoadResult:
        data = await file.read()
        result = service.load_upload(file.filename or "upload.bin", data, source_note=source)
        if not result.accepted and result.rejected:
            return JSONResponse(status_code=400, content=result.model_dump())  # type: ignore[return-value]
        return result

    @app.post("/steward/load-folder", response_model=StewardLoadResult, tags=["steward"])
    def steward_load_folder(
        service: ServiceDep,
        _actor: StewardDep,
        path: Annotated[str | None, Form()] = None,
        source: Annotated[str | None, Form()] = None,
        dry_run: Annotated[bool, Form()] = False,
    ) -> StewardLoadResult:
        """Load from the USB mount point (or another folder the steward names)."""
        folder = Path(path) if path else service.config.steward_inbox
        try:
            return service.load_folder(folder, source_note=source, dry_run=dry_run)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/steward/audit", tags=["steward"])
    def steward_audit(service: ServiceDep, _actor: StewardDep) -> dict[str, Any]:
        return {"entries": service.store.audit_trail()}

    # -- print ---------------------------------------------------------------
    @app.get("/print/howto.html", response_class=HTMLResponse, tags=["print"])
    def print_howto_html(
        service: ServiceDep,
        language: str | None = None,
        page: str = "a5",
    ) -> HTMLResponse:
        paper = PaperPack(service.pack, service.catalogue)
        return HTMLResponse(paper.howto_html(language=language, page=page))

    @app.get("/print/howto.pdf", tags=["print"])
    def print_howto_pdf(
        service: ServiceDep,
        language: str | None = None,
        page: str = "a5",
    ) -> Response:
        paper = PaperPack(service.pack, service.catalogue)
        try:
            pdf = paper.howto_pdf(language=language, page=page)
        except PdfUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return Response(
            content=pdf,
            media_type="application/pdf",
            headers={"Content-Disposition": 'inline; filename="cak-howto.pdf"'},
        )

    # -- kiosk (no JavaScript) ----------------------------------------------
    @app.get("/", response_class=HTMLResponse, tags=["kiosk"])
    def kiosk(request: Request, service: ServiceDep, language: str | None = None) -> HTMLResponse:
        return HTMLResponse(_render_kiosk(request, service, language, None))

    @app.post("/", response_class=HTMLResponse, tags=["kiosk"])
    def kiosk_ask(
        request: Request,
        service: ServiceDep,
        q: Annotated[str, Form(min_length=1, max_length=400)],
        language: Annotated[str | None, Form()] = None,
    ) -> HTMLResponse:
        response = service.answer(q, language)
        return HTMLResponse(_render_kiosk(request, service, response.language, response))


def _render_kiosk(
    request: Request,
    service: NodeService,
    language: str | None,
    response: AgentResponse | None,
) -> str:
    manifest = service.pack.manifest
    lang = service.catalogue.resolve_language(language)

    def t(key: str, **fmt: object) -> str:
        return service.catalogue.get(key, lang, **fmt)

    examples = service.catalogue.get("kiosk.examples", lang)
    example_list = (
        examples
        if isinstance(examples, list)
        else [
            t("kiosk.example_hours"),
            t("kiosk.example_where"),
        ]
    )

    template = request.app.state.jinja.get_template("kiosk.html.j2")
    return template.render(
        language=lang,
        t=t,
        pack={
            "name": manifest.name,
            "locale_id": manifest.locale_id,
            "pack_version": manifest.pack_version,
            "legal_banner": manifest.legal_banner,
            "authority": {
                "name": manifest.authority.name,
                "phone": manifest.authority.phone,
                "address": manifest.authority.address,
            },
        },
        response=response,
        answer_blocks=_answer_blocks(response),
        examples=example_list,
    )


def _answer_blocks(response: AgentResponse | None) -> list[dict[str, str]]:
    """Split the answer markdown into paragraphs and quotes for the no-JS view.

    The kiosk renders markdown itself rather than shipping a renderer: the only
    markup the extractive generator emits is bold headings and block quotes.
    """
    if response is None or response.status != "ok":
        return []
    blocks: list[dict[str, str]] = []
    for line in response.answer_markdown.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(">"):
            blocks.append({"kind": "quote", "text": stripped.lstrip("> ").strip()})
        else:
            blocks.append({"kind": "text", "text": stripped.strip("*")})
    return blocks
