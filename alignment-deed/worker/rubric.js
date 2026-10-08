/**
 * The scoring rubric, shared by every client. RUBRIC.md is the specification;
 * this file is its executable form. The model scores the axes, this file does
 * the arithmetic and picks the role.
 */

export const AXES = [
  { id: "mission", label: "Mission fit", weight: 0.26,
    def: "How closely the funder's stated purpose, priorities and review criteria match this organization's actual mission and current programs. Not what it could pivot to." },
  { id: "place", label: "People & place", weight: 0.14,
    def: "Whether the populations and geography the funder requires are the ones this organization already serves and can document serving." },
  { id: "capacity", label: "Capacity & budget", weight: 0.20,
    def: "Whether the organization can absorb and spend the award: budget size against award size, staffing, cash flow under reimbursement, and any match or cost-share requirement." },
  { id: "evidence", label: "Evidence & outcomes", weight: 0.16,
    def: "Whether the organization already holds the track record, data and evaluation capability the solicitation asks applicants to show." },
  { id: "compliance", label: "Compliance readiness", weight: 0.12,
    def: "Registrations, audit status, indirect cost rate, procurement and reporting burden against what this funder requires of a direct recipient." },
  { id: "competition", label: "Competitive position", weight: 0.12,
    def: "How this applicant reads against the field the solicitation is written to attract, including any stated preference or priority points." }
];

export const AX = Object.fromEntries(AXES.map(a => [a.id, a]));

const clamp = (n, lo, hi) => Math.max(lo, Math.min(hi, Number.isFinite(+n) ? +n : lo));

/** First match wins. See RUBRIC.md for why the third rule reads as it does. */
export function deriveRole(axes, hardCount) {
  const g = id => (axes.find(a => a.id === id) || { score: 0 }).score;
  const m = g("mission"), cap = g("capacity"), comp = g("compliance"),
        ev = g("evidence"), cp = g("competition");
  if (m < 40) return "PASS";
  if (hardCount && m < 55) return "PASS";
  if (hardCount) return m >= 70 ? "SUBRECIPIENT" : "CO_APPLICANT";
  if (comp < 45 || cap < 35) return "SUBRECIPIENT";
  if (cap < 55 || ev < 50 || cp < 40) return "CO_APPLICANT";
  if (m >= 65 && cap >= 55 && comp >= 55) return "LEAD";
  return "CO_APPLICANT";
}

/** Takes the model's raw analysis plus the org profile; returns the scored result. */
export function computeScore(raw, profile) {
  const byId = {};
  for (const a of raw.axes || []) if (a && AX[a.id] && !byId[a.id]) byId[a.id] = a;

  const axes = AXES.map(def => {
    const got = byId[def.id] || {};
    return {
      id: def.id,
      score: clamp(Math.round(got.score || 0), 0, 100),
      finding: got.finding || "No finding returned for this axis.",
      evidence: got.evidence || ""
    };
  });

  // A grant well over an organization's annual budget is the most common way a
  // small nonprofit damages itself by winning. Not the model's call to make.
  const budget = +profile.budget || 0;
  const awardMax = +((raw.rfp || {}).awardMax) || 0;
  const cap = axes.find(a => a.id === "capacity");
  let ratio = null, capNote = "";
  if (budget > 0 && awardMax > 0) {
    ratio = awardMax / budget;
    if (ratio > 1.5 && cap.score > 40) {
      capNote = `Held at 40: the award ceiling is ${ratio.toFixed(1)}x annual budget.`;
      cap.score = 40;
    } else if (ratio > 0.75 && cap.score > 60) {
      capNote = `Held at 60: the award ceiling is ${Math.round(ratio * 100)}% of annual budget.`;
      cap.score = 60;
    }
  }

  const blockers = (raw.blockers || []).filter(b => b && b.issue);
  const hard = blockers.filter(b => b.severity === "hard");
  let total = Math.round(axes.reduce((s, a) => s + a.score * AX[a.id].weight, 0));
  let totalNote = "";
  if (hard.length && total > 34) {
    totalNote = `Held at 34 by ${hard.length} hard blocker${hard.length > 1 ? "s" : ""}.`;
    total = 34;
  }

  return { axes, total, totalNote, ratio, capNote, blockers, hard,
           role: deriveRole(axes, hard.length) };
}

export const RFP_CAP = 60000;

export function analysisPrompt(rfpText, p) {
  const caps = Array.isArray(p.caps) && p.caps.length ? p.caps.join("; ") : "none confirmed";
  const axisDefs = AXES.map(a => `- ${a.id} ("${a.label}"): ${a.def}`).join("\n");
  return `You are a grant strategist advising a small organization on whether to pursue one funding opportunity. You are paid to be accurate, not encouraging. Return JSON only, no prose outside it.

=== ORGANIZATION ===
Name: ${p.name || "not stated"}
Legal status: ${p.status || "not stated"}
Years operating: ${p.years || "not stated"}
Annual budget (USD): ${p.budget || "not stated"}
Staff FTE: ${p.staff || "not stated"}
Geography served: ${p.geo || "not stated"}
Populations served: ${p.pop || "not stated"}
Mission: ${p.mission || "not stated"}
Programs: ${p.programs || "not stated"}
Evidenced outcomes: ${p.outcomes || "not stated"}
Past funders: ${p.funders || "not stated"}
Compliance readiness (only these are confirmed in place): ${caps}

=== OPPORTUNITY (verbatim, may be truncated) ===
"""
${String(rfpText).slice(0, RFP_CAP)}
"""

=== HOW TO JUDGE ===
${axisDefs}

Scoring discipline:
- Score each axis 0-100 against its own definition. 70+ means a reviewer would see the fit without being told. 40-69 means it has to be argued. Below 40 means it is a stretch. Most real pairings land between 35 and 70; do not inflate.
- Every finding must rest on words from the opportunity text or the organization profile. Quote the opportunity in "evidence" (under 25 words, verbatim). If the text does not address something, say "not stated in the solicitation" and score on what is there.
- Absent compliance items are a real cost. Anything not listed as confirmed above is not in place.
- Call a blocker "hard" only when the solicitation states a requirement this organization fails right now. Everything else is "soft".
- Opportunities under "leads" are recollection, not a live database: give the recurring program or funder family, and set confidence to "low" unless you are sure the program exists and recurs. Never state a deadline for a lead.

Return exactly this JSON:
{"rfp":{"funder":"","program":"","awardMin":0,"awardMax":0,"awardNote":"","deadline":"","matchRequired":"","eligibleApplicants":"","family":"","issueAreas":[""]},
 "headline":"",
 "modelRole":"LEAD|CO_APPLICANT|SUBRECIPIENT|PASS",
 "rationale":"",
 "axes":[{"id":"mission","score":0,"finding":"","evidence":""}],
 "blockers":[{"severity":"hard|soft","issue":"","whatToDo":""}],
 "partner":{"needed":true,"profile":"","theyBring":"","youBring":"","split":"","whereToLook":""},
 "language":{"terms":[{"term":"","theirMeaning":"","yourPhrasing":""}],"opening":"","say":[""],"avoid":[""],"themes":[""]},
 "nextSteps":[""],
 "leads":[{"program":"","funder":"","why":"","cycle":"","keywords":"","confidence":"high|medium|low"}]}

Field notes:
- awardMin/awardMax: dollars as integers, 0 if the text does not say. awardNote: the award language verbatim, short.
- family: the funding family in a few words.
- headline: one sentence, under 20 words, on what decides this.
- axes: all six ids, once each, in the order given above.
- language.terms: 8 to 12 rows. "term" is a word or phrase the solicitation itself uses. "theirMeaning" is what the funder means by it in this document. "yourPhrasing" is a specific sentence fragment this organization can honestly write using that term, drawing on its real programs.
- language.opening: 110 to 160 words. The opening paragraph of the narrative, in this organization's voice, using the solicitation's vocabulary and naming its real programs and geography. No placeholders, no brackets.
- say: 5 things to foreground. avoid: 5 framings that will cost points with this reviewer. themes: the themes the solicitation requires every applicant to address.
- nextSteps: 4 to 6 concrete actions in order, each doable this month.
- leads: 4 to 6 other opportunities or funder families worth checking.`;
}

export function extractPrompt(text) {
  return `Read this organization's own website copy and fill in a grant-readiness profile. Return JSON only.

WEBSITE COPY
"""
${String(text).slice(0, 24000)}
"""

Rules:
- Use only what the copy states or clearly implies. Leave a field as "" when the copy does not say. Never invent a budget, a headcount, or an outcome number.
- "outcomes" collects only figures or results the copy actually claims, verbatim where possible.
- "status" is one of: 501c3, fiscally-sponsored, 501c4, government, school, tribal, for-profit, unincorporated. Use "" if the copy does not say.

Return exactly:
{"name":"","status":"","years":"","budget":"","staff":"","geo":"","pop":"","mission":"","programs":"","outcomes":"","funders":""}
- years, budget, staff: digits only, or "".
- geo: places served. pop: who is served. mission: one or two sentences in the organization's own words.
- programs: the named programs and services, semicolon separated.
- funders: named funders, foundations or agencies credited anywhere in the copy, comma separated.`;
}
