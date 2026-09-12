# Steward runbook

You are the steward. You own the device and the files on it. This is everything you need
to run a Civic Node, in the order you will need it.

You do **not** need to be a programmer. You do need to be able to say "I don't know, here
is the number to call" without flinching — that is the hardest and most important part of
the job.

---

## Rule one, before anything technical

> **Do not interpret ID laws. Do not tell anyone they cannot vote. Hand them the official
> contact card.**

If someone asks whether they can vote — because of a conviction, an address, a name
change, an ID, immigration status, anything — the answer is:

> "I can't answer that, and neither can this device. Only the election office can.
> Here is their number."

That is not you being unhelpful. Getting it wrong sends someone away who could have
voted, or sends someone to a polling place who then gets turned away in front of their
neighbours. The device is built to refuse these questions for the same reason.

The node will always give you the office's number. So will the printed card. Hand over
the card.

---

## Daily checks (2 minutes)

1. Is the device powered and the light on?
2. Open the kiosk page. Is the banner there? Ask "when is early voting?" — do you get an
   answer with a citation?
3. Are there printed how-to cards on the table? Print more if you are below about 20.

If the kiosk does not load: unplug the power, wait ten seconds, plug it back in, wait one
minute. If it still does not load, use paper for the day and call your technical contact.

## Weekly checks (10 minutes)

```bash
cak-node health --config /etc/cak/node.toml
cak-node verify --config /etc/cak/node.toml
```

`health` should say `"status": "ok"`. `verify` should say both `chain: OK` and `files: OK`.

**If `verify` says a file is tampered**, the file on disk is not the one that was logged.
That means someone changed it outside the proper flow. Do not fix it by editing the file:

1. Write down what it says.
2. Re-load the correct file from the authority through the USB flow below. That makes a
   new log record, which is the honest history.
3. Tell whoever you report to. This is the check working, not the device failing.

---

## Updating official files from a USB stick

Target: under 15 minutes. Do this whenever the election office publishes something new —
and always check for updates in the week before early voting opens and again two days
before election day.

### 1. Get the files from the authority

Download from the election office's own website, or collect printed documents from the
office and scan them. Put each file in a folder on the USB stick using the same filename
the node already uses:

```
/usb/
  hours.md
  sites.md
  contacts.md
  polling_places.csv
```

**Do not edit the documents.** Do not summarise them, do not "clean them up", do not add
your own notes. The whole promise of this device is that it repeats what the authority
published. If something is confusing, that is worth reporting to the office — not
worth fixing yourself.

### 2. Note where each file came from

For each file, write a line on paper: the web address or office you got it from, and the
date. You will type this as the "source" when you load it, and it goes into the permanent
record.

### 3. Load it

Plug in the stick, then either use the steward page in the browser, or run:

```bash
# See what would change, without changing anything
cak-node load-folder --config /etc/cak/node.toml /media/cak-usb --dry-run

# Do it, recording where the files came from
cak-node load-folder --config /etc/cak/node.toml /media/cak-usb \
  --source "Springfield Civic Board website, 2026-09-12"
```

You will get back a list of files `accepted`, `unchanged` (identical to what was already
there — normal, nothing to do), and `rejected` with a reason.

Some file types are refused on purpose: spreadsheets (`.xlsx`), programs (`.exe`, `.sh`),
and databases. If you have a spreadsheet of polling places, save it as CSV first. If a
file you need is rejected and you do not know why, ask before working around it.

### 4. Check it took

```bash
cak-node ask --config /etc/cak/node.toml "when is early voting?"
cak-node verify --config /etc/cak/node.toml
```

The answer should reflect the new file, and `verify` should be clean. Then print fresh
paper cards if the hours or locations changed:

```bash
cak-node print-howto --config /etc/cak/node.toml --out howto.pdf --page a5
```

---

## Answering people at the desk

**What the device is for:** where to vote, when, what the hours are, how to contact the
office, what languages and accessibility help exist — anything the official documents on
it actually say.

**What it will refuse, correctly:**

| Someone asks | The device says | What you say |
| --- | --- | --- |
| "Am I eligible?" / "Can I vote with a felony?" | Refuses, gives the office number | "Only the office can answer that. Here's their card." |
| "Who should I vote for?" | Refuses | "This device is nonpartisan and so am I while I'm on this desk." |
| "Am I registered?" | Refuses, gives the office number | "The office can look that up. Here's the number." |
| "Is my ID good enough?" | Refuses, gives the office number | "I'm not allowed to interpret ID rules. Please call them." |
| Anything not in the files | "I don't have that in the official files on this device" | Hand over the contact card. |

**When the device says "I don't know", that is a correct answer.** It means the files do
not cover it. Do not fill the gap from memory, from what a colleague said, or from a
website you found. Hand over the card.

## The "I don't know" exercise

Before you run a desk, do this out loud with someone. The deployment checklist asks for
it, and it takes five minutes.

Have them ask you, one after another:

1. "When is early voting?" — you find the answer and read the citation aloud.
2. "I've got a felony conviction, can I vote?" — you say the refusal sentence.
3. "There's no street address where I live. What do I put?" — you check whether the files
   say anything; if not, you hand over the card.
4. "Who's the better candidate?" — you decline.
5. "The library site was closed yesterday, is that right?" — you log it as a field report
   and tell them to call the office to confirm.

If you got through those without guessing once, you are ready.

---

## Field reports

If someone tells you a site was closed, moved, had an hour-long line, or turned someone
away, log it. Use the KoBo form on a phone, or text the short code:

```
WAIT site01 45        report a 45-minute wait
CLOSED site02         report a site closed
OPEN site02           report it open again
HELP                  get the codes back
```

Two rules: **no names, ever** — not in notes, not in photos — and a reason code is what
the person said happened, **not a legal finding**. "Turned away — ID" means they told you
it was about ID. It does not mean the turn-away was lawful or unlawful. That distinction
protects the person and protects you.

Photos: no faces. A photo of a locked door or a printed sign is useful. A photo of people
in a line is not, and it creates a record of who was where.

---

## Things to do, and not do

**Do**

- Keep the device charged; keep a power bank with it if the power is unreliable
- Keep paper cards stocked, in every language the pack ships
- Keep the office's phone number visible without touching the device at all
- Report anything the device could not answer, so the next pack can cover it

**Do not**

- Edit files in `official/` directly
- Add a document the authority did not publish
- Tell anyone they can or cannot vote
- Take a photo of anyone's ID, form or ballot
- Write down a resident's name, address, or phone number in connection with this device
- Let anyone use the steward password who has not been trained

## If something goes wrong

| Symptom | What to do |
| --- | --- |
| Kiosk won't load | Power cycle. Wait a minute. Use paper. Call your contact. |
| Answers look out of date | Check `cak-node health` for `pack_version`; re-load from USB. |
| `verify` reports tampering | Do not edit the file. Re-load the correct one. Report it. |
| Someone asks something the files don't cover | Contact card. Log it as a gap. |
| You are asked for resident data | Say no. There isn't any on the device, and that's by design. |
| Someone claims the device told them something wrong | Ask what they asked. The citation shows the exact file and section. If the file is wrong, that is the office's to fix; if the device is wrong, report it as a bug — it is a serious one. |

Your technical contact and the election office number belong at the top of a printed copy
of this page, taped to the inside of the box. Do that before the first day.
