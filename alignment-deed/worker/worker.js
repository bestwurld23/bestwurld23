/**
 * Alignment Deed — self-hosted API.
 *
 * This exists for the one thing the published page cannot do: fetch a website.
 * An artifact runs in a sandbox that blocks outbound requests, so the page asks
 * people to paste their copy. A worker has a network, so it can read the site
 * itself and hand back the same profile shape.
 *
 * Deploy: wrangler deploy. Set ANTHROPIC_API_KEY as a secret and MODEL as a var.
 */

import { analysisPrompt, extractPrompt, computeScore } from "./rubric.js";

const MAX_PAGES = 5;
const MAX_CHARS = 40000;
const FETCH_TIMEOUT_MS = 10000;
const INTERESTING = /(about|program|service|impact|mission|what-we-do|who-we-are|our-work|team)/i;

export default {
  async fetch(request, env) {
    const origin = env.ALLOWED_ORIGIN || "*";
    const cors = {
      "access-control-allow-origin": origin,
      "access-control-allow-methods": "POST, OPTIONS",
      "access-control-allow-headers": "content-type"
    };
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });

    const json = (body, status = 200) =>
      new Response(JSON.stringify(body), { status, headers: { ...cors, "content-type": "application/json" } });

    if (request.method !== "POST") return json({ error: "POST only" }, 405);
    if (!env.ANTHROPIC_API_KEY) return json({ error: "ANTHROPIC_API_KEY is not set on this worker." }, 500);
    if (!env.MODEL) return json({ error: "MODEL is not set on this worker." }, 500);

    const path = new URL(request.url).pathname.replace(/\/+$/, "");
    let body;
    try { body = await request.json(); }
    catch { return json({ error: "Body must be JSON." }, 400); }

    try {
      if (path === "/profile") {
        const site = String(body.siteUrl || "").trim();
        if (!/^https?:\/\//i.test(site)) return json({ error: "siteUrl must be an http(s) URL." }, 400);
        const { text, pages } = await crawl(site);
        if (text.length < 200) {
          return json({ error: "Too little readable text at that address. Paste the copy instead.", pages }, 422);
        }
        const profile = await ask(env, extractPrompt(text));
        return json({ profile: { ...profile, site }, pages, chars: text.length });
      }

      if (path === "/analyze") {
        const profile = body.profile || {};
        let rfpText = String(body.rfpText || "");
        if (!rfpText && /^https?:\/\//i.test(String(body.rfpUrl || ""))) {
          rfpText = (await crawl(String(body.rfpUrl), 1)).text;
        }
        if (rfpText.length < 200) return json({ error: "Supply rfpText (200+ characters) or a readable rfpUrl." }, 400);
        const raw = await ask(env, analysisPrompt(rfpText, profile));
        if (!Array.isArray(raw.axes)) return json({ error: "The model returned an unusable shape." }, 502);
        return json({ raw, score: computeScore(raw, profile) });
      }

      return json({ error: "Unknown path. Use /profile or /analyze." }, 404);
    } catch (err) {
      return json({ error: String(err && err.message || err) }, 502);
    }
  }
};

/* ---------- crawling ---------- */

async function get(url) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), FETCH_TIMEOUT_MS);
  try {
    const res = await fetch(url, {
      signal: ctl.signal,
      redirect: "follow",
      headers: { "user-agent": "AlignmentDeed/1.0 (+grant alignment reader)", accept: "text/html,*/*" }
    });
    if (!res.ok) return "";
    if (!/text\/html|text\/plain/i.test(res.headers.get("content-type") || "")) return "";
    return await res.text();
  } catch {
    return "";
  } finally {
    clearTimeout(timer);
  }
}

/** Minimal robots.txt: the paths disallowed for every agent. */
async function disallowed(origin) {
  const txt = await get(origin + "/robots.txt");
  if (!txt) return [];
  const out = [];
  let appliesToUs = false;
  for (const line of txt.split(/\r?\n/)) {
    const m = line.match(/^\s*(user-agent|disallow)\s*:\s*(.*?)\s*$/i);
    if (!m) continue;
    if (m[1].toLowerCase() === "user-agent") appliesToUs = m[2] === "*";
    else if (appliesToUs && m[2]) out.push(m[2]);
  }
  return out;
}

export async function crawl(startUrl, limit = MAX_PAGES) {
  const start = new URL(startUrl);
  const blocked = await disallowed(start.origin);
  const allowed = u => !blocked.some(b => new URL(u).pathname.startsWith(b));

  const seen = new Set();
  const queue = [start.href];
  const chunks = [];
  const pages = [];
  let discovered = false;

  while (queue.length && pages.length < limit && chunks.join(" ").length < MAX_CHARS) {
    const url = queue.shift();
    if (seen.has(url) || !allowed(url)) continue;
    seen.add(url);

    const html = await get(url);
    if (!html) continue;
    const text = toText(html);
    if (text.length > 120) { chunks.push(text); pages.push(url); }

    // Discover from the first document that loads, not the first that had
    // enough text: plenty of homepages are a hero image and six words.
    if (!discovered) {
      discovered = true;
      for (const href of links(html, url)) {
        if (seen.has(href) || queue.includes(href)) continue;
        if (new URL(href).origin !== start.origin) continue;
        if (INTERESTING.test(new URL(href).pathname)) queue.push(href);
      }
    }
  }

  return { text: chunks.join("\n\n").slice(0, MAX_CHARS), pages };
}

function links(html, base) {
  const out = [];
  for (const m of html.matchAll(/<a\b[^>]*\bhref\s*=\s*["']([^"'#]+)["']/gi)) {
    try { out.push(new URL(m[1], base).href); } catch { /* skip unparseable href */ }
  }
  return out;
}

function toText(html) {
  return html
    .replace(/<(script|style|noscript|svg|head)\b[\s\S]*?<\/\1>/gi, " ")
    .replace(/<!--[\s\S]*?-->/g, " ")
    .replace(/<\/(p|div|li|h[1-6]|section|article|br|tr)>/gi, "\n")
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/gi, " ").replace(/&amp;/gi, "&").replace(/&lt;/gi, "<")
    .replace(/&gt;/gi, ">").replace(/&quot;/gi, '"').replace(/&#39;/gi, "'")
    .replace(/&#(\d+);/g, (_, d) => String.fromCharCode(+d))
    .replace(/[ \t ]+/g, " ")
    .replace(/\n\s*\n\s*\n+/g, "\n\n")
    .trim();
}

/* ---------- the model ---------- */

async function ask(env, prompt) {
  const res = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-api-key": env.ANTHROPIC_API_KEY,
      "anthropic-version": "2023-06-01"
    },
    body: JSON.stringify({
      model: env.MODEL,
      max_tokens: 8000,
      messages: [{ role: "user", content: prompt }]
    })
  });

  if (!res.ok) throw new Error(`Model request failed (${res.status}): ${(await res.text()).slice(0, 300)}`);

  const data = await res.json();
  const text = (data.content || []).filter(b => b.type === "text").map(b => b.text).join("");
  return parseJson(text);
}

/** The reply is usually bare JSON, sometimes fenced, occasionally with a sentence around it. */
function parseJson(text) {
  const tries = [text];
  const fence = text.match(/```(?:json)?\s*([\s\S]*?)```/);
  if (fence) tries.push(fence[1]);
  const first = text.search(/[{[]/);
  const last = Math.max(text.lastIndexOf("}"), text.lastIndexOf("]"));
  if (first !== -1 && last > first) tries.push(text.slice(first, last + 1));
  for (const t of tries) {
    try { return JSON.parse(t.trim()); } catch { /* try the next shape */ }
  }
  throw new Error("The model's reply held no parseable JSON.");
}
