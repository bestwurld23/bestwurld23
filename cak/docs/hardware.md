# Hardware

Normative source: PRD §6.4. Everything here is commodity hardware you can buy in one
order and replace locally, which matters more than performance: a node that cannot be
repaired by the organization hosting it is a node that dies quietly.

## Reference node — Raspberry Pi 5

| Item | Spec | Notes |
| --- | --- | --- |
| Board | Raspberry Pi 5, 8 GB | 4 GB works for the extractive generator; 8 GB for a local model |
| Storage | 128 GB+ A2 microSD, or NVMe via the M.2 HAT | NVMe if you can afford it; SD cards wear out |
| Power | Official 27 W USB-C PSU | Under-powering a Pi 5 causes failures that look like software bugs |
| Case | Passive heatsink case, or active cooler | A kiosk runs all day in a warm room |
| OS | Raspberry Pi OS 64-bit (Debian 12) | |
| Network | Optional; Ethernet or Wi-Fi | No inbound internet required, ever |
| Peripherals | USB stick for updates; optional thermal or laser printer | |
| Optional | 4G dongle | For *outbound* sync only, never for serving |

The whole application is a Python process, a SQLite file and a folder of documents. It
idles at well under 200 MB with the extractive generator.

## Also runs on

- Debian 12 / Ubuntu 22.04+ on x86_64 — use `deploy/compose/` (labs, a spare office PC)
- Any VM with 1 vCPU and 1 GB RAM, for a jurisdiction that would rather host it themselves

## Bill of materials

See `hardware-bom.csv` next to this file for a machine-readable version.

### Minimum node (no local model)

| Item | Qty | Indicative USD |
| --- | --- | --- |
| Raspberry Pi 5, 4 GB | 1 | 60 |
| 27 W USB-C power supply | 1 | 12 |
| 64 GB A2 microSD | 1 | 10 |
| Passive case with heatsink | 1 | 12 |
| 32 GB USB stick (pack updates) | 2 | 12 |
| **Total** | | **~106** |

### Recommended node (local model, kiosk use)

| Item | Qty | Indicative USD |
| --- | --- | --- |
| Raspberry Pi 5, 8 GB | 1 | 80 |
| 27 W USB-C power supply | 1 | 12 |
| 128 GB A2 microSD *or* 256 GB NVMe + M.2 HAT | 1 | 18 / 55 |
| Active cooler case | 1 | 15 |
| 32 GB USB stick | 2 | 12 |
| USB power bank, 20 000 mAh PD | 1 | 40 |
| 7" touchscreen (kiosk) | 1 | 70 |
| **Total** | | **~250-290** |

### Solar option (intermittent power)

For a chapter house, a rural clinic, or an LMIC deployment where mains power is
unreliable. Sized for 24-hour operation with one cloudy day of reserve.

| Item | Qty | Indicative USD | Notes |
| --- | --- | --- | --- |
| 100 W solar panel | 1 | 70 | Pi 5 under load draws ~7-12 W |
| PWM/MPPT charge controller, 12 V | 1 | 25 | MPPT if the budget allows |
| 12 V 20 Ah LiFePO4 battery | 1 | 90 | ~240 Wh; LiFePO4 tolerates heat and cycling |
| 12 V → 5 V/5 A USB-C buck converter | 1 | 15 | Must sustain 5 V 5 A for a Pi 5 |
| Fused wiring, connectors | 1 | 20 | Fuse the battery side |
| **Total** | | **~220** | on top of the node |

Sizing arithmetic, so you can adapt it: a Pi 5 serving a kiosk averages roughly 8 W, or
about 190 Wh/day. A 100 W panel at four effective sun-hours yields ~400 Wh/day, which
covers the node and recharges the battery. A 240 Wh battery carries one full day with no
sun. Add panel before you add battery — it is cheaper per usable watt-hour.

A cheaper alternative that covers most of the need: run on mains with a 20 000 mAh USB-C
PD power bank in pass-through mode as a UPS. That is about four hours of runtime and
protects against the power cuts that corrupt SD cards.

## Storage budget

| Content | Size |
| --- | --- |
| OS + Python + dependencies | ~3 GB |
| Locale pack, text documents | 1-50 MB |
| Locale pack with scanned PDFs | 50-500 MB |
| `cak.db` (counters, audit, report queue) | under 50 MB in practice |
| Change log (`changelog.jsonl`) | ~1 KB per record |
| GGUF model, 3B class, Q4 | ~2 GB |
| GGUF model, 7B class, Q4 | ~4-5 GB |

64 GB is comfortable without a model. 128 GB with one.

## Local model notes (Phase 1)

The default generator is **extractive** — it quotes the official files and adds nothing.
It needs no model, no GPU and no accelerator, and it cannot hallucinate. Start there; a
node with no model still satisfies the product's first goal.

When you add a model, set `generator = "ollama"` in `node.toml` and name the model. A
3B-class quantised model (`llama3.2:3b` or similar) is the sweet spot on a Pi 5: it fits
in RAM alongside the app and answers in a few seconds on CPU. 7B-class runs but is slow
enough that residents at a desk notice.

Two constraints that are not about speed:

- **Licence.** Do not redistribute model weights on a prepared SD image unless the
  model's licence allows it. Document the download URL instead and have the steward pull
  it once. PRD §22.3 has this as an open question; it is a legal question, not a technical
  one.
- **The citation lock applies either way.** Whatever the model emits is checked against
  the retrieved excerpts before it reaches a resident, and an answer carrying an
  unsupported number is discarded entirely. A better model makes answers read better; it
  does not widen what the node is allowed to say.

## Measuring latency on your own hardware

PRD §17.9 asks for latency to be documented rather than promised. CI timings on a shared
cloud runner say nothing about a Pi, so measure on the device:

```bash
pytest tests/test_load.py -v          # records latency as test properties
```

Measure with your real pack, since retrieval cost scales with the number of chunks, and
with your real generator — the extractive path and a 3B model differ by orders of
magnitude. Write the numbers down in your deployment record. Do not publish a target
you have not measured on the hardware you shipped.

## Physical setup

- Put the device where staff can see it and residents cannot walk off with it.
- Label it, in plain language, with what it is and what it is not.
- Tape the election office's phone number to the outside, so it is readable when the
  device is off or broken.
- Keep two USB sticks: one for the current pack, one for the previous. A rollback you
  can do by hand beats a rollback you have to be talked through on the phone.
- Enable LUKS if the device sits somewhere it can walk away from — and read the trade-off
  in `docs/threat-model.md` T5 first, because an encrypted node cannot reboot unattended
  after a power cut, and in these terrains power cuts are normal.
