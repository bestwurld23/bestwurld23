# Provenance — dev-fixture official documents

This directory holds the documents the Civic Agent is allowed to quote. It is
excluded from the retrieval index: this file is provenance prose, not an
official document (PRD §10.1).

**Everything in this fixture pack is fictional.** The Springfield Civic Board
does not exist, `555-0100` is a reserved fictional number, and no real person,
address or voter record appears anywhere in it. That is a requirement, not a
convenience: PRD §18 Phase 0 says do not scrape real PII into the fixture.

| File | What it is | Sidecar |
| --- | --- | --- |
| `hours.md` | Early voting and election day hours | `hours.md.meta.yaml` |
| `sites.md` | Voting locations and accessibility notes | `sites.md.meta.yaml` |
| `contacts.md` | Board phone, address, language and access help | `contacts.md.meta.yaml` |

## How a real pack differs

In a real deployment a steward downloads these documents from the authority and
does not edit them. Each file keeps a `*.meta.yaml` sidecar recording where it
came from, when it was retrieved, and its SHA-256 (PRD §10.4). If a file has to
be modified — OCR of a scanned PDF, for example — the original and the
derivative are both stored, and the agent prefers the original.

Whether the documents may be redistributed in the pack at all depends on the
authority's terms. When they may not be, the pack ships empty and the steward
loads the files from a USB stick on first boot (PRD §15.2).
