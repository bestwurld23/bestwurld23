"""``cak-node`` — run or inspect a Civic Node from the terminal.

cak-node serve         --config ./deploy/compose/node.toml
cak-node ask           --config ... "when is early voting?"
cak-node load-folder   --config ... /media/cak-usb
cak-node verify        --config ...
cak-node health        --config ...
cak-node hash-password
cak-node print-howto   --config ... --out howto.html
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path

from cak_node.config import ConfigError, NodeConfig, hash_password, new_steward_password
from cak_node.pack import PackValidationError
from cak_node.printing import PaperPack, PdfUnavailable
from cak_node.service import NodeService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cak-node",
        description="Civic Node: offline civic information. Not a voting machine.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def with_config(p: argparse.ArgumentParser) -> argparse.ArgumentParser:
        p.add_argument("--config", type=Path, default=Path("/etc/cak/node.toml"))
        return p

    serve = with_config(sub.add_parser("serve", help="run the local HTTP server"))
    serve.add_argument("--bind", default=None)
    serve.add_argument("--port", type=int, default=None)

    ask = with_config(sub.add_parser("ask", help="ask the agent one question"))
    ask.add_argument("question")
    ask.add_argument("--language", default=None)
    ask.add_argument("--json", action="store_true", dest="as_json")

    load = with_config(sub.add_parser("load-folder", help="load official files from a folder/USB"))
    load.add_argument("folder", type=Path)
    load.add_argument("--source", default=None, help="provenance note for the log")
    load.add_argument("--dry-run", action="store_true")

    with_config(sub.add_parser("verify", help="verify the change log and official/ on disk"))
    with_config(sub.add_parser("health", help="print the health payload"))

    pw = sub.add_parser("hash-password", help="hash a steward password for node.toml")
    pw.add_argument("--password", default=None, help="omit to be prompted")
    pw.add_argument("--suggest", action="store_true", help="suggest a password and hash it")

    printer = with_config(sub.add_parser("print-howto", help="render the how-to card"))
    printer.add_argument("--out", type=Path, required=True, help=".html or .pdf")
    printer.add_argument("--language", default=None)
    printer.add_argument("--page", default="a5", help="a5 | a4 | letter | 5x7")

    return parser


def _service(args: argparse.Namespace) -> NodeService:
    return NodeService(NodeConfig.from_toml(args.config))


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from cak_node.app import create_app

    config = NodeConfig.from_toml(args.config)
    if args.bind:
        config.bind = args.bind
    if args.port:
        config.port = args.port
    app = create_app(config)
    print(f"Civic Node on http://{config.bind}:{config.port} — pack {config.locale_pack}")
    if config.is_localhost_only:
        print("Bound to localhost only. Set bind + steward_password_hash for LAN/kiosk access.")
    uvicorn.run(app, host=config.bind, port=config.port, log_level="info")
    return 0


def cmd_ask(args: argparse.Namespace) -> int:
    service = _service(args)
    response = service.answer(args.question, args.language)
    if args.as_json:
        print(response.model_dump_json(indent=2))
    else:
        print(f"[{response.status}] {response.answer_markdown}\n")
        for citation in response.citations:
            print(f"  — {citation.title} ({citation.file_id} {citation.locator})")
            print(f"    {citation.excerpt}")
        if response.status != "ok":
            print(f"  office: {response.office.name} {response.office.phone or ''}")
        print(f"\n{response.disclaimer}")
    service.close()
    return 0 if response.status in {"ok", "i_dont_know"} else 1


def cmd_load_folder(args: argparse.Namespace) -> int:
    service = _service(args)
    result = service.load_folder(args.folder, source_note=args.source, dry_run=args.dry_run)
    print(json.dumps(result.model_dump(), indent=2))
    service.close()
    return 0 if not result.rejected else 1


def cmd_verify(args: argparse.Namespace) -> int:
    service = _service(args)
    chain = service.changelog.verify()
    files = service.verify_files()
    print(f"chain: {'OK' if chain.ok else 'FAILED'} ({chain.record_count} records)")
    for problem in chain.problems:
        print(f"  ! {problem}")
    print(f"files: {'OK' if files.ok else 'FAILED'} ({files.checked} checked)")
    for item in files.mismatched:
        print(f"  ! tampered: {item['path']}")
        print(f"      log says {item['expected_sha256']}")
        print(f"      on disk  {item['actual_sha256']}")
    for path in files.unlogged:
        print(f"  ! present on disk but never logged: {path}")
    for path in files.missing:
        print(f"  ! in the log but missing from disk: {path}")
    service.close()
    return 0 if chain.ok and files.ok else 1


def cmd_health(args: argparse.Namespace) -> int:
    service = _service(args)
    print(service.health().model_dump_json(indent=2))
    service.close()
    return 0


def cmd_hash_password(args: argparse.Namespace) -> int:
    if args.suggest:
        password = new_steward_password()
        print(f"suggested password: {password}")
    else:
        password = args.password or getpass.getpass("steward password: ")
    if not password:
        print("error: empty password", file=sys.stderr)
        return 2
    print("\nAdd this line to node.toml:")
    print(f'steward_password_hash = "{hash_password(password)}"')
    return 0


def cmd_print_howto(args: argparse.Namespace) -> int:
    service = _service(args)
    paper = PaperPack(service.pack, service.catalogue)
    out = Path(args.out)
    try:
        if out.suffix.lower() == ".pdf":
            out.write_bytes(paper.howto_pdf(language=args.language, page=args.page))
        else:
            out.write_text(
                paper.howto_html(language=args.language, page=args.page), encoding="utf-8"
            )
    except PdfUnavailable as exc:
        print(f"error: {exc}", file=sys.stderr)
        service.close()
        return 2
    print(f"wrote {out}")
    service.close()
    return 0


_COMMANDS = {
    "serve": cmd_serve,
    "ask": cmd_ask,
    "load-folder": cmd_load_folder,
    "verify": cmd_verify,
    "health": cmd_health,
    "hash-password": cmd_hash_password,
    "print-howto": cmd_print_howto,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _COMMANDS[args.command](args)
    except (ConfigError, PackValidationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
