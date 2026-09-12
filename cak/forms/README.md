# Field Forms

Offline incident and access reporting: wait times, turn-aways, closures.

**We do not write a forms engine** (PRD §7.1, P6). KoBoToolbox and ODK already solve
offline data collection, sync, and Android clients better than a civic-tech side project
will, and they are already installed on the phones of people who do this work. What lives
here is three XLSForm definitions and the rules about what must never go in them.

## The forms

| Form | Purpose |
| --- | --- |
| `cak_wait_time` | How long the line is at a site, and whether it is open |
| `cak_turnaway` | Someone said they were turned away, and what they said the reason was |
| `cak_closure` | A site is closed, moved, or running different hours than published |

Sources are YAML in `src/`; importable spreadsheets are built into `dist/`.

```bash
pip install openpyxl
python forms/build.py --pack packs/dev-fixture --out forms/dist
```

The YAML is the reviewable source of truth. A binary spreadsheet cannot be reviewed in a
pull request, and the site choice list is generated from the locale pack's
`sites.geojson`, so a steward who adds a site to the pack rebuilds the forms rather than
hand-editing a spreadsheet.

## Importing into KoBoToolbox

1. Sign in to your own KoBo server — `kf.kobotoolbox.org`, the humanitarian server, or a
   self-hosted instance. The host organization's account, not ours. There is no CAK
   cloud, and there is no CAK KoBo account.
2. **Projects → New → Upload an XLSForm**, and choose `forms/dist/cak_wait_time.xlsx`.
3. Check the site list came through: open the form, find "Which site?", and confirm the
   choices match your pack.
4. **Deploy** the project.
5. On the phone: install **KoBoCollect** (or **ODK Collect**), add your server URL and
   account, **Get Blank Form**, and select the CAK forms.
6. Fill one in with the network off, to prove it queues. Then **Send Finalized Form** when
   there is signal.

For ODK Central, the flow is the same: **New Project → Create Form → upload the .xlsx →
Publish**.

Screenshots of each step belong in this directory as Phase 1 work (PRD §18, §23).

## Rules for anyone filling these in

These are in the forms themselves, as notes and hints the reporter cannot skip past, and
they are worth stating here too:

- **No names.** Not in a notes field, not in a photo, not "the tall man in the blue coat".
- **No addresses, phone numbers or ID details** of any individual.
- **No faces in photos.** A sign, a locked door, an empty queue: useful. People waiting:
  not useful, and it creates a record of who was where.
- **A reason code is what the person said happened.** It is not a legal finding. "Turned
  away — ID" means they told you it was about ID. Whether that was lawful is not yours,
  or ours, to decide.
- **A closure report is unofficial** until a steward confirms it against a document from
  the election office. Do not tell residents a site has moved on the strength of a report
  alone.

The forms are designed so that following these rules is the path of least resistance:
there is no name field to leave blank, and the sensitive free-text fields carry the
warning in their hint.

## Timestamps

Every form defaults `observed_at` to `now()` and rejects a time more than two hours in the
future or seven days in the past. Cheap Android handsets drift, and a battery pull resets
the clock to the epoch — the PRD calls for flagging an obviously wrong device clock, and
it is far better caught at entry than discovered during analysis.

## The SMS path

A feature phone cannot run KoBoCollect. The short codes cover the same ground for the two
most time-critical reports:

```
WAIT site01 25     report a 25-minute wait
CLOSED site02      report a site closed
OPEN site02        report it open again
HELP               get the codes back
```

Codes are defined per locale in `packs/<locale>/sms/codes.yaml` and may be in the local
language. Parsing is implemented in `sms/` and tested in `tests/test_sms_parser.py`;
gateway integration (`twilio`, `africas_talking`, `local_modem`) is Phase 2.

SMS payloads carry no names and no phone numbers. The sender's number is the gateway's
business and never reaches CAK's queue.

## Where submissions go

To an endpoint the **steward** chooses: their KoBo, their MinIO, their ministry server.
The default is nowhere (PRD §7.4).

The node keeps a local append-only store-and-forward queue in `cak.db` for reports that
arrive by SMS while there is no backhaul. Sync marks a row forwarded; it never edits or
deletes the report, and a retried sync cannot lose or duplicate one. The queue rejects any
payload containing a forbidden field name, or a value that matches a name, address, phone,
SSN or date-of-birth pattern — see `tests/test_sms_parser.py` and `tests/test_no_pii.py`.

## A note on `cak_turnaway`

This is the form most likely to be misused, in both directions. Filled in carelessly it
becomes a file on individual people, which is the thing this project exists not to build.
Filled in as designed it is one of the few records anyone keeps of access failures at a
polling place — which is, historically, exactly what has been missing.

The difference is entirely in the discipline of the reporter. Train for it.
