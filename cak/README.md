# Civic Access Kit (CAK)

Civic Access Kit is offline-first, open-source civic **information** infrastructure for
low-connectivity communities. **It is not a voting machine.**

It does four things, all of them on a box a local organization owns:

- **Answers questions** about where, when and how to participate — only from official
  documents on the device, always with a citation, and "I don't know" plus a phone
  number when the files don't say.
- **Proves the files didn't change** behind anyone's back, through a signed, append-only
  hash chain an auditor can verify with a copy of the log and nothing else.
- **Prints** the same information on paper, because paper works when the power doesn't.
- **Takes field reports** — wait times, closures, turn-aways — offline, and forwards them
  to an endpoint the steward chooses, never to us.

It does **not** cast, transmit, store or count ballots. It does not decide who may vote.
It has no user accounts, no biometrics, and no cloud. See [§2.2 of the PRD](docs/prd.md)
for the full list of things this must never become, and `docs/threat-model.md` for what
it defends against.

---

## Status: Phase 0 complete

| Phase 0 deliverable (PRD §18) | State |
| --- | --- |
| Repo skeleton, licences, PRD in `docs/prd.md` | done |
| `pack.yaml` schema + `packs/dev-fixture/` | done |
| FastAPI `/health`, `/pack`, `/agent/query` (FTS5, LLM stub) | done |
| Citation JSON (PRD §11.3) | done |
| Steward USB/folder load | done |
| Changelog append + verify CLI | done |
| pytest for §17.1–17.5 | done, plus §17.6–17.9 |

Phase 1 (local model via Ollama, kiosk polish, paper PDF, XLSForms in KoBo, Pi
packaging) is next. The Ollama path is written and configurable today; it is not the
default because a node with no model still has to work.

## Quick start

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"

# Ask the fixture pack a question, offline, with no model on the box.
cak-node ask --config deploy/compose/node.toml "When is early voting?"

# Serve the kiosk and the API on localhost.
cak-node serve --config deploy/compose/node.toml
```

Then open <http://127.0.0.1:8080>. The kiosk page uses no JavaScript and no external
assets, so it works on a locked-down library terminal and a 2G phone.

### What a good answer looks like

```console
$ cak-node ask --config deploy/compose/node.toml "When is early voting?"
[ok] **Early voting hours** (official/hours.md)
> Early voting runs on weekdays from 8am to 6pm.

  — Early voting hours (official/hours.md #early-voting-hours)

This is not an official election office. Information is copied from published
official documents. We cannot say if you are eligible to vote.
```

### What a refusal looks like

```console
$ cak-node ask --config deploy/compose/node.toml "Am I eligible if I have a felony?"
[i_dont_know] I cannot say whether someone may vote. Only the election office
decides that. Please contact: Springfield Civic Board, 555-0100, 10 Civic Plaza.
```

That is not a failure. It is the product working: eligibility is a legal determination
that belongs to an election office, and a device that guesses at it in a neighbourhood
that has been purged before is worse than no device at all.

## Repository layout

```
cak/
  node/          Civic Node: FastAPI app, agent, retrieval, steward flow   AGPL-3.0
  changelog/     Append-only signed hash chain + CLI                       Apache-2.0
  sms/           Short-code parser for feature phones                      Apache-2.0
  print/         Paper Pack templates                                      Apache-2.0
  packs/         Locale packs (config, not forks)                          Apache-2.0
  forms/         XLSForm definitions for KoBo / ODK                        Apache-2.0
  deploy/        docker compose (x86) and systemd (Pi)
  docs/          PRD, OpenAPI, pack spec, threat model, runbook, hardware
  tests/         PRD §17 test requirements
```

`node/` is AGPL-3.0-or-later so that a hosted fork stays open to the people it serves.
Everything else is Apache-2.0 so it can be embedded, vendored and re-used freely. Official
documents in a pack remain the property of their authority; see `docs/locale-pack-spec.md`.

## How the agent is kept honest

Four independent mechanisms, because any one of them can be wrong:

1. **Scope guard** — eligibility, partisan, ballot-secrecy and tallying questions are
   refused before retrieval runs, so a high-scoring passage can't be used to answer one.
2. **Retrieval floor** — a passage must cover roughly half the question's content words
   to be answerable at all. See the scoring notes in `node/cak_node/retrieval.py`.
3. **Citation lock** — every sentence of a generated answer is checked back against the
   retrieved excerpts. Numbers are held to a stricter standard than words: a time or a
   phone number that isn't in the files (or in the pack's own contact block) fails the
   whole answer closed.
4. **Change log** — every official file's hash is recorded, so "what did the node say
   last Tuesday" has an answer that does not depend on trusting the operator.

Run `pytest tests/test_citation_lock.py` to see all four exercised, including a
deliberately rogue generator that tries to serve an invented phone number.

## Verifying a node you don't trust

```bash
# Is this file the one the log says was on the node?
cak-changelog find --log /var/lib/cak/changelog.jsonl --file ./hours.md

# Does the whole chain hold, and does the disk match it?
cak-changelog verify --log /var/lib/cak/changelog.jsonl --root /var/lib/cak/pack

# Hand an auditor the log and the public key.
cak-changelog export --log /var/lib/cak/changelog.jsonl --out ./audit
```

The same checks are available over HTTP at `GET /changelog`, `GET /changelog/verify`
and `GET /changelog/verify-files`, without authentication, on purpose.

## Contributing

Read `CONTRIBUTING.md` first, then `docs/prd.md` §2.2. Pull requests that add ballot
handling, eligibility logic, biometrics, resident accounts, or phone-home telemetry will
be closed on sight — not because they are badly written, but because they are a different
product wearing this one's name.

`SECURITY.md` has the disclosure process. `DEPLOYMENT.md` has the checklist that must be
satisfied before this is installed anywhere outside a lab.
