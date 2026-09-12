# Locale pack specification (v1)

Normative source: PRD §10 and §11. This document is the implementation reference; where
the two disagree, the PRD wins and this file is the bug.

A locale pack is how one codebase serves Englewood, a rural county, a chapter house and
an invited electoral commission. **A pack is configuration, not a fork.** If supporting a
community needs a code change, the pack format is wrong.

## Layout

```
packs/<locale_id>/
  pack.yaml            # manifest (required)
  PACK.sig             # detached Ed25519 signature over pack contents (Phase 3)
  official/            # the only documents the agent may quote (required)
    README.md          # provenance prose; never indexed, never cited
    hours.md
    polling_places.csv
    sample_ballot.pdf
    <file>.meta.yaml   # provenance sidecar, one per document
  i18n/                # UI and agent strings (required)
    en.yaml
    es.yaml
  sites/
    sites.geojson      # RFC 7946 FeatureCollection
  print/               # generated or source print artifacts
  sms/
    codes.yaml
  keys/
    pack_public.pem    # pack maintainer's public key
```

A `.cakpack` is a zip of that directory. Phase 0 loads directories; signed zip
distribution is Phase 3.

## `pack.yaml`

Validated by `cak_node.pack.PackManifest`. **Unknown keys are rejected** — a typo like
`retrival_min_score` would otherwise look configured and silently do nothing.

```yaml
cak_pack_version: 1              # must be 1
locale_id: us-il-chicago         # lowercase, dash-separated, 2-5 segments
name: Chicago, Illinois, USA
authority:
  name: Chicago Board of Elections   # required
  url: https://chicagoelections.gov
  phone: "312-269-7900"
  address: "69 W Washington St, Chicago, IL"
languages: [en, es]              # at least one
default_language: en             # must appear in languages
retrieval_min_score: 0.35        # 0.0-1.0
legal_banner: >-
  This device is not an official election office. It only repeats published
  official information.
time_zone: America/Chicago
sites_file: sites/sites.geojson  # must exist if named
official_dir: official/
i18n_dir: i18n/
sms:
  enabled: true
  wait_code: WAIT
  closed_code: CLOSED
  help_code: HELP
does_not:                        # must include the two below
  - determine_eligibility
  - collect_ballots
pack_version: "2026.09.12"
files_license: >-
  Official documents remain copyright of the authority.
  Pack metadata CC-BY-4.0.
```

### Why `does_not` is enforced

The loader **refuses to start** on a pack that does not declare both
`determine_eligibility` and `collect_ballots` in `does_not`. A deployment cannot quietly
present itself as an eligibility authority by omitting the disclaimer, and the check lives
in code rather than in a review checklist because review checklists are not run at boot.

Additional entries are allowed and encouraged (`tally_votes`, `store_personal_data`).

### What `retrieval_min_score` means

The score is **question coverage**, not raw BM25 — see the scoring notes at the top of
`node/cak_node/retrieval.py` for why BM25's IDF term is unusable on a corpus of three
documents. In practice:

| Threshold | Effect |
| --- | --- |
| 0.25 | A passage covering about a third of the question's content words can answer |
| **0.35** (default) | About half — recommended starting point |
| 0.50 | Most of the question must be addressed; more "I don't know", fewer stretches |

Raise it for a pack whose documents are long and general. Lower it only after reading what
the node starts answering, and never to suppress an "I don't know" that is correct.

## `official/` — the knowledge boundary

Everything the agent can say comes from here. Nothing else on the device is searchable.

Indexed types: `.md`, `.txt`, `.csv`, `.html`, `.pdf` (PDF needs the `pdf` extra).
Never indexed: `README.md` (provenance prose) and `*.meta.yaml` (sidecars).

Documents are chunked by structure, and the **locator** in a citation points somewhere a
person can actually look:

| Type | Chunking | Locator |
| --- | --- | --- |
| Markdown | By heading, then by paragraph up to ~900 chars | `#heading-anchor` |
| CSV | Header row repeated with each block of 25 rows | `rows 2-26` |
| PDF | One chunk per page | `p.3` |
| HTML | Tags stripped, packed into sections | `section 2` |

A markdown chunk's title is the full heading path — "Where to vote — Springfield Library",
not just "Springfield Library" — because the document-level heading usually says what the
file is *about*, and dropping it loses both retrieval signal and the context a reader
needs to trust the citation.

### Provenance sidecars (PRD §10.4)

Each document should have `<filename>.meta.yaml`:

```yaml
title: Early voting hours          # overrides the derived title
source_url: https://chicagoelections.gov/en/early-voting.html
retrieved_at: 2026-09-01
sha256: "13d891db…"                # of the document as retrieved
authority: Chicago Board of Elections
notes: "Downloaded by steward; not modified."
is_derivative: false               # true for OCR or other transformations
```

If a document must be modified (OCR of a scan, for example), keep **both** the original
and the derivative, mark the derivative `is_derivative: true`, and the agent prefers the
original.

`tests/test_pack_schema.py` fails if a sidecar's recorded hash no longer matches its file:
a stale provenance claim is worse than none, because it looks checked.

### Redistribution

Official documents belong to their authority. Only ship them inside a pack if the
authority's terms allow it. When they do not, ship the pack with an empty `official/` and
have the steward load the documents from a USB stick on first boot — the node handles that
case normally, and the change log records exactly what arrived.

## `i18n/<lang>.yaml`

Nested keys, looked up as dotted paths. Lookup order is: requested language → pack
default → the key itself. **Nothing here ever raises.** A kiosk in a chapter house must
not white-screen because a translator skipped a line.

Keys the node uses:

```yaml
banner:
  not_an_election_office: ...     # overrides legal_banner for display
agent:
  dont_know: ...                  # {authority} {phone} {address} {url}
  refuse_eligibility: ...
  refuse_partisan: ...
  refuse_injection: ...
  refuse_ballot_secrecy: ...
  refuse_tally: ...
kiosk:
  title, skip_to_form, ask_label, ask_placeholder, ask_button,
  answer_heading, citations_heading, examples_heading, office_heading,
  pack_label, print_link, changelog_link, examples (list)
print:
  howto_title, where_when, ask_the_office, by_text_message, minutes,
  wheelchair, no_sites_listed, nonpartisan, pack_label
steward:
  do_not_interpret: ...
field_form:
  reason_code_help: ...
```

Placeholders are filled with `str.format`; a missing placeholder degrades to the
unformatted template rather than raising. A pack shipping two languages should have both
complete — `tests/test_i18n.py` checks that every English key exists in Spanish for the
fixture pack, and a real pack should carry the same test.

## `sites/sites.geojson`

RFC 7946 `FeatureCollection`. Feature properties:

```json
{
  "id": "ward-16-site-03",
  "name": "Englewood Library",
  "hours": "07:00-19:00",
  "address_text": "1 Main St, Chicago",
  "accepts_non_street_address_note": null,
  "wheelchair": true,
  "languages": ["en", "es"],
  "early_voting": true,
  "election_day": true
}
```

`accepts_non_street_address_note` exists because on tribal lands and for people without a
street address, "what do I put on the form" is the question that decides whether someone
participates. Fill it **only** with text an official document supports; leave it `null`
otherwise. The node does not infer it.

`id` is what SMS reporters type (`WAIT ward-16-site-03 25`), so keep it short, lowercase,
and free of characters a feature phone makes painful.

## `sms/codes.yaml`

```yaml
wait_code: WAIT
closed_code: CLOSED
open_code: OPEN
help_code: HELP
gateway: none        # none | twilio | africas_talking | local_modem
examples:
  - "WAIT site01 25"
```

Codes are per locale and may be in the local language (`ESPERA`, `CERRADO`). Replies stay
under 160 GSM-7 characters so they arrive as one message, and they repeat the disclaimer
even at that length.

## `keys/`

A real pack carries `keys/pack_public.pem` and a detached `PACK.sig`. The fixture pack is
deliberately unsigned — a signing key in a public repository is not a signing key. See
`packs/dev-fixture/keys/README.md`.

## Validating a pack

```bash
cak-node health --config your-node.toml      # file count, pack version, index state
cak-node ask    --config your-node.toml "when is early voting?"
cak-node verify --config your-node.toml      # chain + files on disk
pytest tests/test_pack_schema.py
```

Check three things before a deployment, in this order:

1. The questions residents actually ask return `ok` with the right file.
2. Eligibility and partisan questions return `i_dont_know` **with the office phone number
   in the language the resident is reading**.
3. `cak-node verify` is clean, so the verifier will mean something later.
