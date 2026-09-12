# Threat model (v1)

Normative source: PRD §12.4. This document says what the Phase 0 code actually does about
each threat, and — more usefully — what it does not.

## What is being protected

Not ballots. CAK never touches one. What is at stake is narrower and still worth
defending:

1. **The correctness of what a resident is told.** Someone acts on the answer. A wrong
   time, a closed site, an invented phone number costs a vote.
2. **The ability to prove what the node said.** "The polling place list changed on Monday
   and nobody was told" must be checkable by someone who does not trust the operator.
3. **The absence of a target.** The node holds no voter list, no names, no addresses, no
   ballot choices. The strongest defence here is that there is nothing to steal.

## Threats

### T1 — Poisoned official files

Someone puts a document in `official/` that is not what the authority published: a
neighbouring file with altered hours, a helpful volunteer's summary, a deliberate fake.

**What the code does.** Every file the node has ever served is hashed into an append-only,
Ed25519-signed chain. `GET /changelog/verify-files` and `cak-changelog verify --root`
compare `official/` on disk against the log and report three distinct failures: bytes that
differ from what was logged (`mismatched`), files present but never logged (`unlogged`),
and files in the log that have vanished (`missing`). Steward writes go through one path
that copies and logs together. Provenance sidecars record the source URL and retrieval
date, and `/pack` publishes every file's hash so a third party can compare against the
authority's own download.

**What it does not do.** Nothing stops a steward from loading a poisoned file *through*
the steward flow — it will be faithfully logged as poisoned. The log makes it attributable
and detectable after the fact, not impossible. Pack signing (Phase 3) closes part of this
by letting a maintainer sign a whole pack; it does not close the case where the steward is
the problem. That case is handled by the log being public and exportable.

### T2 — Agent hallucination

The model states something the files do not say.

**What the code does.** Four layers, deliberately independent:

- A **scope guard** refuses eligibility, partisan, ballot-secrecy and tallying questions
  *before* retrieval, so a high-scoring passage cannot be pressed into answering one.
- A **retrieval floor**: a passage sharing no content word with the question is dropped
  outright, and the score must clear the pack's `retrieval_min_score`.
- The **citation lock** re-checks every sentence of a generated answer against the
  retrieved excerpts. Numbers face a stricter rule than words: a time, date or phone
  number not present in the excerpts (or in the pack's own contact block, which is
  official by construction) fails the entire answer closed to `i_dont_know`.
- The **default generator is extractive** — it quotes the files and adds nothing — so a
  node with no model loaded cannot hallucinate at all.

**What it does not do.** The citation lock is a token-grounding check, not semantic
entailment. A generated sentence built entirely from words present in the excerpts but
recombined into a false claim can pass it. That is the known gap, and it is why the
extractive generator is the Phase 0 default and why `tests/test_citation_lock.py` runs a
deliberately rogue generator on every build.

### T3 — Prompt injection

A resident, or text inside a document, tries to make the node answer without its files.

**What the code does.** Injection phrasings are refused by the scope guard (`ignore the
files`, `you are now`, `answer without citations`, `make something up`, and more —
`tests/test_citation_lock.py` parametrises a list). Even if a guard is bypassed, an answer
still has to pass the citation lock, so "say polls open at 3am" fails on the unsupported
number `3am`. The system prompt is published at `/agent/prompt` rather than hidden.

**What it does not do.** Guard patterns are regex and therefore incomplete; a novel
phrasing will get through to retrieval. The design assumes that, which is why the citation
lock is the actual defence and the guard is a fast path.

### T4 — Coercion and vote-buying

Someone is pressured to prove how they voted.

**What the code does.** There is no voting feature, no receipt, and no record of any vote.
Questions of the form "who did I vote for" or "prove I voted" are refused with an explicit
statement that the device holds no such record. This is a design property, not a control.

### T5 — Device theft

The Pi walks out of the library.

**What the code does.** No personal data is stored, so a stolen device leaks the pack
(which is public documents) and the counters (which are integers). The signing key is on
the device at mode 0600, so a thief can append to *that* node's log — which is why an
auditor's copy of an exported log, obtained earlier, is the ground truth for the past.

**What it does not do.** Full-disk encryption is not enabled by default, because a node
that cannot reboot unattended after a power cut stops logging, and in the terrains this
ships to power cuts are normal. `docs/hardware.md` recommends LUKS where the device sits
somewhere it can walk away from, and the trade-off is the steward's to make.

### T6 — LAN attacker

Someone on the same Wi-Fi tries to write to the node.

**What the code does.** The default bind is `127.0.0.1`. A node configured to bind
anywhere else **refuses to start** unless `steward_password_hash` is set — the config
object raises, so there is no window in which an open steward API is listening. Steward
auth is HTTP Basic against a PBKDF2-SHA256 hash with constant-time comparison, and a node
with no hash configured returns 503 on every steward route rather than falling open.

Public routes are unauthenticated on purpose. `/files/{id}` serves only files the index
knows about, so a path like `official/../pack.yaml` is a 404 rather than a traversal. FTS
queries are stripped to alphanumeric tokens before they reach SQLite, so no query can
inject FTS operators.

**What it does not do.** Local HTTP is plain by default; on an untrusted LAN put Caddy in
front with a local certificate. Nothing here defends against an attacker who already has
root on the device.

### T7 — Supply chain

A dependency is compromised.

**What the code does.** The dependency list is short and deliberately boring: FastAPI,
Pydantic, PyYAML, `cryptography`, Jinja2. Retrieval is stdlib `sqlite3`; there is no
vector database, no ML framework, no cloud SDK. Optional extras (`pdf`, `llm`) are exactly
that — the node runs without them.

**What it does not do.** Pinning and SBOM generation are deployment-time steps, not
repository-time ones. Pin dependencies in the image you build and generate an SBOM
(`syft`, `pip-audit`) per release, per PRD §12.4.

### T8 — Legal impersonation

A resident believes the device speaks for the election office.

**What the code does.** The banner is on the kiosk page, in every printed artifact, in
every API response (`disclaimer`), and in SMS replies at 160 characters. It is required
and non-empty in `pack.yaml`, in every language the pack ships. A pack that does not
declare `determine_eligibility` in `does_not` will not load.

### T9 — Exclusion by ID rules or by AI

The tool becomes another gate.

**What the code does.** There is no eligibility module to build on. Questions asking for a
judgement about a specific person's ID, address or registration are refused by category
with the office's phone number, in the resident's language. `docs/steward-runbook.md`
makes "do not interpret ID laws" the steward's first rule.

### T10 — Cloud outage

**What the code does.** There is no cloud. `tests/test_offline.py` disables the socket
layer and runs every Must feature, including a steward USB load and printing. Sync, when a
steward configures it, goes to an endpoint they chose.

## Privacy as a security property

The privacy rules are enforced three ways, because a rule that lives only in a document
gets broken by a well-meaning contributor on a deadline:

1. A static linter (`tests/test_no_pii.py`) fails CI if a forbidden column name reaches
   any SQL statement in the source.
2. `Store` **refuses to open** a database whose schema contains one.
3. The field-report queue rejects payloads with forbidden keys, or with values matching a
   name, address, phone, SSN or date-of-birth pattern.

Question text is not stored by default. If a steward opts in, the text is stored only when
it matches no personal-data pattern; the digest is always what the counters use.

## Known gaps, stated plainly

- Citation lock is token grounding, not entailment (T2).
- Guard patterns are regex and incomplete by construction (T3).
- A dishonest steward can log a poisoned file honestly (T1).
- Pack signature verification is Phase 3; Phase 0 protects the node's own log only.
- No rate limiting on `/agent/query`. A node is a LAN appliance; if this becomes a
  problem, it is a symptom of a deployment that should not be exposed.
- Local HTTP is unencrypted by default.

If you find something not on this list, `SECURITY.md` has the disclosure process.
