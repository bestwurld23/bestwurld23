# Contributing

Thank you for wanting to work on this. Two things to read before you write code: the
non-goals in `docs/prd.md` §2.2, and the product principles in §3. They decide most
review outcomes.

## What will not be merged

No matter how good the implementation:

- Casting, transmitting, storing or tallying ballots for public office
- Internet, app or blockchain voting
- Anything that decides eligibility, citizenship, or a "fraud score"
- Biometric capture for identity-as-vote
- A public record of how a person voted, or any receipt that enables coercion
- A central, project-owned voter file
- Resident accounts, social logins, or fine-tuning a model on chat logs
- Phone-home telemetry, or making a cloud service the system of record

If you need one of these, you need a different project. Say so in an issue and we will
try to point you at the right one — MOSIP, OpenCRVS, KoBo, Ushahidi, or a certified
tabulator like VotingWorks.

## Ground rules that come from the PRD

- **Offline is the default.** If a feature stops working with the network unplugged, it
  is not done. `tests/test_offline.py` disables the socket layer outright; keep it green.
- **Compose, don't conquer.** We ship XLSForms for KoBo and ODK. We do not write a forms
  engine.
- **Locale packs are configuration.** If supporting a community requires a code change,
  the pack format is wrong and that is the bug to fix.
- **Paper and SMS ship with the app.** A software-only change to a resident-facing flow
  is incomplete until the printable and text-message paths reflect it.
- **Accessibility is not phase two.** WCAG 2.2 AA, 18px minimum body text on the kiosk,
  icons alongside text on paper, and at least two languages per pack where the community
  needs them.

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest
ruff check . && ruff format --check .
```

The test suite runs in a few seconds and needs no network, no model and no device.

### Code standards (PRD §21.3)

- Type hints on everything public.
- Ruff for lint and format; both run in CI.
- No `print` in merged code outside the two CLI entry points.
- Small functions. Retrieval stays isolated from generation so tests can stub the model —
  do not reach for an LLM inside `retrieval.py`.
- Comments explain constraints the code cannot show. Do not narrate what the next line
  does.

### Tests we will ask you for

PRD §17 lists nine test requirements and the suite implements all of them. A change that
touches the agent, the log, the pack loader or storage needs a test in the matching file:

| Area | File |
| --- | --- |
| Citation lock, scope guard, grounding | `tests/test_citation_lock.py` |
| Retrieval and scoring | `tests/test_retrieval.py` |
| Change log integrity | `tests/test_changelog.py` |
| Offline behaviour | `tests/test_offline.py` |
| Pack schema validation | `tests/test_pack_schema.py` |
| SMS parsing | `tests/test_sms_parser.py` |
| Privacy and the no-PII linter | `tests/test_no_pii.py` |
| i18n fallback | `tests/test_i18n.py` |
| Concurrency | `tests/test_load.py` |

If you loosen a guard — widen what the agent will answer, relax the grounding threshold,
add a file type the steward may load — say so explicitly in the pull request description
and add the test that pins the new boundary.

## Adding a locale pack

Packs are configuration, so you do not need to touch `node/` at all. Copy
`packs/dev-fixture/`, follow `docs/locale-pack-spec.md`, and run:

```bash
cak-node ask --config your-node.toml "when is early voting?"
```

Do not commit real personal data, ever, including in test fixtures. Do not commit an
authority's documents unless their terms allow redistribution; if they do not, ship the
pack empty and let the steward load the files from a USB stick.

If the pack is for a community you are not part of, read `DEPLOYMENT.md` first. A written
invitation is not paperwork, it is the difference between infrastructure and imposition.

## Commit and pull request style

- One concern per pull request.
- Explain *why*, not just what. "Fixes retrieval" tells a reviewer nothing; "off-topic
  questions scored above threshold because BM25's IDF collapses on a ten-chunk corpus"
  tells them everything.
- Note which PRD section the change serves, or which one you are proposing to amend.

## Code of conduct

`CODE_OF_CONDUCT.md` applies to every space this project uses.
