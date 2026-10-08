# The alignment rubric

This file is the specification. The web page inlines it; any other client should
read it from here. Change a weight here first, then in the clients.

## Why a rubric at all

Given an RFP and an organization, a language model will produce encouragement.
It is agreeable by default, and "this looks like a strong fit" is the cheapest
thing it can say. The rubric exists to make the model commit to numbers against
fixed definitions, and to hand the arithmetic to code that cannot be flattered.

The division of labour:

| Step | Who does it |
|---|---|
| Read the solicitation, quote it, score each axis | the model |
| Weight the axes and total them | the page |
| Apply the award-to-budget override | the page |
| Apply the hard-blocker cap | the page |
| Choose the recommended role | the page |
| Write the rationale and the language kit | the model |

The model's own role recommendation is collected but not used. When it disagrees
with the rules, the page says so and shows both. Disagreement is information.

## The six axes

| id | Axis | Weight | Scores |
|---|---|---|---|
| `mission` | Mission fit | 26% | How closely the funder's stated purpose, priorities and review criteria match the organization's actual mission and current programs. Not what it could pivot to. |
| `place` | People & place | 14% | Whether the populations and geography the funder requires are the ones the organization already serves and can document serving. |
| `capacity` | Capacity & budget | 20% | Whether the organization can absorb and spend the award: budget against award size, staffing, cash flow under reimbursement, match or cost-share. |
| `evidence` | Evidence & outcomes | 16% | Whether the organization already holds the track record, data and evaluation capability the solicitation asks applicants to show. |
| `compliance` | Compliance readiness | 12% | Registrations, audit status, indirect cost rate, procurement and reporting burden against what this funder requires of a direct recipient. |
| `competition` | Competitive position | 12% | How this applicant reads against the field the solicitation is written to attract, including stated preferences or priority points. |

Weights sum to 1.00.

Scoring bands given to the model: 70+ means a reviewer would see the fit without
being told; 40–69 means it has to be argued; below 40 is a stretch. The model is
told most real pairings land between 35 and 70.

Every axis finding must carry `evidence`: a verbatim quote under 25 words from
the solicitation, or from the organization profile. An axis the solicitation does
not address is scored on what is there and the finding says so.

## Deterministic overrides

**Award-to-budget ratio.** With both an annual budget and an award ceiling, the
page computes `ratio = awardMax / annualBudget`:

- `ratio > 1.5` → capacity is held at a maximum of 40
- `ratio > 0.75` → capacity is held at a maximum of 60

A grant well over an organization's annual budget is the most common way a small
nonprofit damages itself by winning, so this override is not the model's to make.

**Hard blockers.** A blocker is `hard` only when the solicitation states a
requirement the organization fails today. One or more hard blockers caps the
weighted total at 34, whatever the axes say. Everything else is `soft`: real
cost, not a gate.

## Role rules

Evaluated in order, first match wins. `m` mission, `cap` capacity, `comp`
compliance, `ev` evidence, `cp` competition, after the overrides above.

```
m < 40                             → PASS
hard blockers and m < 55           → PASS
hard blockers                      → m >= 70 ? SUBRECIPIENT : CO_APPLICANT
comp < 45 or cap < 35              → SUBRECIPIENT
cap < 55 or ev < 50 or cp < 40     → CO_APPLICANT
m >= 65 and cap >= 55 and comp >= 55 → LEAD
otherwise                          → CO_APPLICANT
```

The interesting rule is the third. Excellent mission fit plus a hard blocker is
not a rejection: it is the definition of a subrecipient. The work belongs to this
organization; someone else's eligibility carries it. Weaker mission fit with the
same blocker means co-applicant, because the organization has to bring more than
delivery to be worth including.

## The language kit

The highest-value output and the one most tools skip. Three parts:

1. **Term mapping** — 8 to 12 rows of `term` / `theirMeaning` / `yourPhrasing`.
   The term is a phrase the solicitation itself uses. The meaning is what this
   funder means by it in this document, which is often not the sector-wide
   meaning. The phrasing is a sentence fragment this organization can honestly
   write using that term, drawing on its real programs.
2. **Draft opening** — 110 to 160 words in the organization's voice, using the
   solicitation's vocabulary, naming real programs and real geography. No
   placeholders, no brackets.
3. **Say / avoid / required themes** — five each, plus the themes every applicant
   must address.

The instruction that does the work is "honestly". A term mapping that invents
capacity is worse than no mapping, because it survives into a submitted proposal.

## Leads

The model is told explicitly that leads are recollection and not a live database:
give the recurring program or funder family, set confidence to `low` unless sure
the program exists and recurs, and never state a deadline. Clients render each
lead with live search links rather than presenting it as a confirmed opportunity.
