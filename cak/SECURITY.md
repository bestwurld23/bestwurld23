# Security policy

## Reporting a vulnerability

Report privately. Do not open a public issue for anything that could be used against a
node that is currently deployed in a community.

- Email: `security@` the project maintainer's domain, or use GitHub's private
  vulnerability reporting on this repository.
- Include: what you found, how to reproduce it, and what an attacker gets. A proof of
  concept against `packs/dev-fixture` is ideal; please do not test against a live
  community node you do not operate.

Expect an acknowledgement within 5 working days and an assessment within 15. We will tell
you what we plan to do and when, and we will credit you unless you ask us not to.

**Patch targets** (PRD §12.4): 90 days for CVEs in anything exposed over the node's local
HTTP surface, faster for anything that breaks the citation lock, the change log, or the
privacy guarantees below.

## What we consider a vulnerability

In rough order of severity:

1. **Anything that makes the node state something the official files do not say** — a
   bypass of the scope guard, the retrieval floor, or the citation lock. An answer that
   invents an address, a time or a phone number is the worst outcome this project has,
   because someone acts on it.
2. **Anything that lets an unauthenticated party write to `official/`** or otherwise
   change what the node serves.
3. **Change-log forgery** — editing, reordering or truncating records in a way
   `cak-changelog verify` does not catch.
4. **Any path by which personal data reaches disk, logs, telemetry, or the network.**
   The node is designed so that it mostly is not a controller of personal data; a bug
   that changes that is a serious bug.
5. Ordinary web vulnerabilities in the local HTTP surface: path traversal in
   `/files/{id}`, injection through the FTS query, authentication bypass on steward
   routes, XSS in the kiosk page.

## Out of scope

- Physical access to the device. A node is a small computer in a library; whoever holds
  it can rewrite its disk. That is why the log is signed and exportable, and why we
  recommend LUKS in `docs/hardware.md`. It is a mitigated risk, not an eliminated one.
- Denial of service by flooding a LAN you are already on.
- The absence of features we deliberately do not build (PRD §2.2). "It cannot count
  ballots" is not a vulnerability.
- Social engineering of a steward. Real, and addressed by training in
  `docs/steward-runbook.md`, but not a software issue.

## Security practices in this repository

- No secrets in git. Signing keys are generated on the device at first boot, mode 0600,
  and never committed. `packs/dev-fixture/keys/README.md` explains why the fixture pack
  is deliberately unsigned.
- Dependencies are declared in `pyproject.toml` and should be pinned in deployment images.
  Generate an SBOM before each release (`syft` or `pip-audit`), per PRD §12.4.
- Steward passwords are stored as PBKDF2-SHA256 hashes, never plaintext, and a node bound
  to anything other than localhost refuses to start without one.
- The test suite treats the privacy rules as executable: `tests/test_no_pii.py` fails CI
  if a personal-data column reaches `cak.db`, and the runtime refuses to open a database
  whose schema contains one.

## Coordinated disclosure and deployed nodes

Nodes are offline by design and update from a USB stick. That means a fix in this
repository does not reach the field on its own. When we publish a security fix we will
also publish a short, plain-language steward notice describing what to do, so an
organization running a node without an engineer on staff can act on it.
