# Keys — dev-fixture

This fixture pack is **unsigned on purpose**. There is no `pack_public.pem` and
no `PACK.sig` here, because a signing key committed to a public repository is
not a signing key — it is a liability, and it would teach exactly the wrong
habit to anyone reading this as an example.

A real pack carries `keys/pack_public.pem` and a detached `PACK.sig` over the
pack contents, signed by the pack maintainer (Ed25519, PRD §10.1, §11.1). The
private half never leaves the maintainer's machine.

Signed `.cakpack` distribution lands in Phase 3 (PRD §18). What Phase 0 ships
is the other half of the same guarantee: the node's own change log, whose
genesis record carries the public key of the steward key generated on first
boot, so every file the node has ever served can be checked against a signed
hash chain. See `docs/threat-model.md`.

## What the node does today

On first boot the node generates `steward.ed25519` (mode 0600) next to its
config, writes a genesis record carrying the matching public key, and logs the
hash of every official file it shipped with. Export the public half for an
auditor with:

    cak-changelog export --log /var/lib/cak/changelog.jsonl --out ./audit
