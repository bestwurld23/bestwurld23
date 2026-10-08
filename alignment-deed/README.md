# Alignment Deed

Paste a grant solicitation. Get back a recommended role (lead, co-applicant,
subrecipient, or pass), a weighted rubric that shows its working, the gates that
would stop you, and the funder's own vocabulary mapped to sentences you can
honestly write.

Built as public infrastructure: no account to create, no backend to pay for, and
the scoring specification is in the repo so anyone can argue with it or fork it.

**Live page:** https://claude.ai/artifact/9EnkpMK7MWaRq6mFrkFUgm

---

## What it actually does

Hand a language model an RFP and an organization and it will tell you this looks
like a strong fit. It is agreeable by default. The point of this tool is to stop
that from happening.

The model is used for what it is good at: reading a 40-page solicitation, finding
the eligibility clause, and quoting it. The judgement that follows is code:

- **Six weighted axes** — mission 26%, capacity 20%, evidence 16%, people and
  place 14%, compliance 12%, competitive position 12%.
- **An award-to-budget override.** If the ceiling is more than 1.5x your annual
  budget, capacity is held at 40 no matter what the model said. Winning a grant
  you cannot float is a way to damage an organization, not a win.
- **A hard-blocker cap.** A requirement you fail today caps the total at 34.
- **Role rules** that read the resulting numbers.

The model also proposes a role. It is recorded and ignored. When the rules
disagree with it, the page shows both and says the rules overrode it.

Full specification, including every threshold: [RUBRIC.md](RUBRIC.md).

## The language kit

The part that most tools skip and most people actually need. For each
solicitation it produces 8 to 12 rows of *their term* → *what this funder means
by it* → *a sentence you can honestly write using it*, plus a drafted opening
paragraph in your own voice, five things to foreground, five framings that cost
you points, and the themes every applicant must address.

Funders score on whether you speak their vocabulary. Most small organizations
lose points to translation, not to merit.

## What it will not do

- **It cannot read your website from the published page.** An artifact runs in a
  sandbox that blocks outbound requests. There is no clever way around this. The
  page asks you to paste your About and Programs copy once and saves it. The
  worker in `worker/` has a network and does crawl, which is what it is for.
- **It does not know what is open right now.** It has no grants database. The
  opportunities it suggests are funder families and recurring programmes from
  the model's recollection, rendered with live search links and a confidence
  label, never with a deadline. Confirm each on the funder's own portal.
- **It is not a decision.** It is a structured second opinion with its reasoning
  exposed so you can disagree with a specific number instead of a vibe.

## Layout

```
alignment-deed/
├── index.html        the whole app: one file, no build step, no dependencies
├── RUBRIC.md         the scoring specification — change weights here first
└── worker/
    ├── rubric.js     executable form of the rubric, shared by any client
    ├── worker.js     HTTP API: /profile crawls a site, /analyze scores an RFP
    └── wrangler.toml deployment config
```

`index.html` inlines the same rubric because an artifact is a single file. When
they drift, `worker/rubric.js` and `RUBRIC.md` are correct.

## Running the page

Open `index.html` in a browser and it renders, with the example reading loaded.
Live readings need the Claude runtime the published artifact provides, so for
those, use the link above or publish your own copy.

Storage, when signed in: your organization profile lives in your own private
subtree and is not readable by anyone else, the artifact's owner included. Saved
runs go there too. The shared library holds only opportunity metadata — funder,
programme, funding family, issue areas — with no organization details attached,
and only for runs you explicitly save.

## Running the worker

The worker exists for the one thing the page cannot do.

```sh
cd worker
wrangler secret put ANTHROPIC_API_KEY
# set MODEL in wrangler.toml to a current Claude model id
wrangler deploy
```

```sh
curl -X POST https://your-worker.workers.dev/profile \
  -H 'content-type: application/json' \
  -d '{"siteUrl":"https://your-org.org"}'

curl -X POST https://your-worker.workers.dev/analyze \
  -H 'content-type: application/json' \
  -d '{"rfpText":"...","profile":{...}}'
```

`/profile` fetches the homepage, reads `robots.txt`, follows up to four
same-origin links whose paths look like about/programs/impact/mission pages, and
returns the same profile shape the page uses. `/analyze` returns `{raw, score}`,
where `score` is the arithmetic above.

Lock `ALLOWED_ORIGIN` to your own front end before you point anything public at
it — the worker spends your API key on every request it accepts.

## Worth building next

1. **Deadline tracking.** The runs list knows what you looked at; it does not yet
   know what you decided or when it closes.
2. **A real opportunity feed.** Grants.gov publishes a bulk XML extract daily.
   Ingesting it into the worker would turn the leads section from recollection
   into search, which is the single biggest honesty upgrade available.
3. **Partner matching across the library.** Two organizations reading the same
   solicitation, one blocked on geography and one blocked on delivery capacity,
   are each other's answer. The data is already shaped for it; what is missing is
   consent to be matched.
4. **Reviewer simulation.** Score a draft narrative against the solicitation's
   own point allocation before submission.

## Licence

Not yet chosen. MIT is the sensible default for infrastructure meant to be
copied; add a LICENSE file to make it real.
