"""``cak-changelog`` — append and verify the process ledger from a terminal.

An auditor with a shell and a copy of ``changelog.jsonl`` can check the whole
chain without running the node (PRD §4.1: auditor persona, browser or CLI).

    cak-changelog init   --log ./changelog.jsonl --key ./steward.ed25519 \\
                         --log-id caklog_dev_2026 --locale-id us-xx-springfield
    cak-changelog append --log ./changelog.jsonl --key ./steward.ed25519 \\
                         --action replace_file --root ./packs/dev-fixture \\
                         official/hours.md
    cak-changelog verify --log ./changelog.jsonl --root ./packs/dev-fixture
    cak-changelog find   --log ./changelog.jsonl --sha256 <hex>
    cak-changelog export --log ./changelog.jsonl --out ./export
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from cak_changelog import keys
from cak_changelog.files import logged_file
from cak_changelog.log import Changelog, ChangelogError, open_log


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--log", required=True, type=Path, help="path to changelog.jsonl")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cak-changelog",
        description="Append-only, signed log of official process files. Never ballots.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="write the genesis record and create a signing key")
    _add_common(p_init)
    p_init.add_argument("--key", required=True, type=Path, help="Ed25519 private key path")
    p_init.add_argument("--log-id", required=True)
    p_init.add_argument("--locale-id", required=True)
    p_init.add_argument("--note", default=None)

    p_append = sub.add_parser("append", help="append a record for one or more files")
    _add_common(p_append)
    p_append.add_argument("--key", required=True, type=Path)
    p_append.add_argument(
        "--action",
        default="replace_file",
        choices=["add_file", "replace_file", "remove_file", "pack_install", "note"],
    )
    p_append.add_argument(
        "--root", required=True, type=Path, help="pack root; paths are recorded relative to it"
    )
    p_append.add_argument("--source", default=None, help="provenance note, e.g. download URL")
    p_append.add_argument("--actor-role", default="steward")
    p_append.add_argument("--note", default=None)
    p_append.add_argument("paths", nargs="*", type=Path, help="files, relative to --root")

    p_verify = sub.add_parser("verify", help="verify the chain, and optionally files on disk")
    _add_common(p_verify)
    p_verify.add_argument("--root", type=Path, default=None, help="pack root to check on disk")
    p_verify.add_argument("--subdir", default="official")
    p_verify.add_argument("--json", action="store_true", dest="as_json")

    p_find = sub.add_parser("find", help="look up a file hash in the log")
    _add_common(p_find)
    group = p_find.add_mutually_exclusive_group(required=True)
    group.add_argument("--sha256")
    group.add_argument("--file", type=Path, help="hash this file, then look it up")

    p_head = sub.add_parser("head", help="print the latest record")
    _add_common(p_head)

    p_export = sub.add_parser("export", help="write changelog.jsonl + changelog.pem")
    _add_common(p_export)
    p_export.add_argument("--out", required=True, type=Path)

    return parser


def cmd_init(args: argparse.Namespace) -> int:
    log = open_log(args.log, args.key, create_key=True)
    private = keys.load_private_key(args.key)
    record = log.genesis(
        log_id=args.log_id,
        locale_id=args.locale_id,
        public_key_pem=keys.public_key_pem(private),
        note=args.note,
    )
    print(f"genesis written: seq={record.seq} record_hash={record.record_hash}")
    print(f"signing key: {args.key} (keep it on the node; back it up offline)")
    return 0


def cmd_append(args: argparse.Namespace) -> int:
    log = open_log(args.log, args.key)
    files = []
    for rel in args.paths:
        rel_posix = Path(rel).as_posix()
        absolute = args.root / rel
        if not absolute.is_file() and args.action != "remove_file":
            print(f"error: {absolute} is not a file", file=sys.stderr)
            return 2
        if absolute.is_file():
            files.append(logged_file(absolute, rel_posix, source=args.source))
    record = log.append(
        action=args.action,
        files=files,
        actor_role=args.actor_role,
        note=args.note,
    )
    print(f"appended: seq={record.seq} action={record.action} files={len(record.files)}")
    print(f"record_hash={record.record_hash}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    log = Changelog(args.log)
    chain = log.verify()
    payload: dict[str, object] = {
        "chain_ok": chain.ok,
        "records": chain.record_count,
        "signatures_checked": chain.signature_checked,
        "problems": chain.problems,
    }
    exit_code = 0 if chain.ok else 1

    if args.root is not None:
        files = log.verify_files(args.root, subdir=args.subdir)
        payload["files_ok"] = files.ok
        payload["files_checked"] = files.checked
        payload["mismatched"] = files.mismatched
        payload["unlogged"] = files.unlogged
        payload["missing"] = files.missing
        if not files.ok:
            exit_code = 1

    if args.as_json:
        print(json.dumps(payload, indent=2))
        return exit_code

    print(
        f"chain: {'OK' if chain.ok else 'FAILED'} ({chain.record_count} records, "
        f"signatures {'checked' if chain.signature_checked else 'not checked'})"
    )
    for problem in chain.problems:
        print(f"  ! {problem}")
    if args.root is not None:
        print(
            f"files: {'OK' if payload['files_ok'] else 'FAILED'} "
            f"({payload['files_checked']} checked)"
        )
        for item in payload["mismatched"]:  # type: ignore[union-attr]
            print(f"  ! tampered: {item['path']}")
            print(f"      log says {item['expected_sha256']}")
            print(f"      on disk  {item['actual_sha256']}")
        for path in payload["unlogged"]:  # type: ignore[union-attr]
            print(f"  ! present on disk but never logged: {path}")
        for path in payload["missing"]:  # type: ignore[union-attr]
            print(f"  ! in the log but missing from disk: {path}")
    return exit_code


def cmd_find(args: argparse.Namespace) -> int:
    from cak_changelog.files import hash_file

    digest = args.sha256 or hash_file(args.file)
    log = Changelog(args.log)
    records = log.find_by_sha256(digest)
    if not records:
        print(f"NOT FOUND: {digest} is not in {args.log}")
        print("This file was not placed on the node through the steward flow.")
        return 1
    print(f"FOUND: {digest}")
    for record in records:
        print(f"  seq={record.seq} ts={record.ts} action={record.action}")
        for file in record.files:
            if file.sha256 == digest.removeprefix("sha256:").lower():
                print(f"    path={file.path} source={file.source or '-'}")
    return 0


def cmd_head(args: argparse.Namespace) -> int:
    record = Changelog(args.log).head()
    if record is None:
        print(f"{args.log} is empty", file=sys.stderr)
        return 1
    print(record.to_json_line())
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    written = Changelog(args.log).export(args.out)
    for path in written:
        print(f"wrote {path}")
    return 0


_COMMANDS = {
    "init": cmd_init,
    "append": cmd_append,
    "verify": cmd_verify,
    "find": cmd_find,
    "head": cmd_head,
    "export": cmd_export,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _COMMANDS[args.command](args)
    except ChangelogError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
