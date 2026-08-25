#!/usr/bin/env node
/**
 * Email Date De-Fuzzer — Stonewall
 * Fuzzy-matches estimated-date Notion emails against CSV-verified dates
 * using aggressive subject normalization, then corrects the dates.
 *
 * Also classifies remaining unmatched as spam/admin/case-related.
 *
 * Usage:
 *   NOTION_TOKEN=ntn_xxx node scripts/email_defuzz.mjs
 *   NOTION_TOKEN=ntn_xxx node scripts/email_defuzz.mjs --dry-run
 */
import https from "https";
import { readFileSync } from "fs";
import { join, dirname } from "path";

const TOKEN = process.env.NOTION_TOKEN || "";
const DB = process.env.NOTION_ALL_EMAIL_DB || "";
const EMAILS_JSON = join(dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Z]:)/, "$1")), "..", "reference_data", "mail", "consolidated_emails.json");
const DRY_RUN = process.argv.includes("--dry-run");

function api(method, path, body) {
  return new Promise((resolve, reject) => {
    const data = body ? JSON.stringify(body) : null;
    const req = https.request({
      hostname: "api.notion.com", path, method,
      headers: { Authorization: `Bearer ${TOKEN}`, "Notion-Version": "2022-06-28", "Content-Type": "application/json", ...(data ? { "Content-Length": Buffer.byteLength(data) } : {}) },
    }, res => {
      let d = "";
      res.on("data", c => (d += c));
      res.on("end", () => {
        if (res.statusCode === 429) {
          const wait = parseFloat(res.headers["retry-after"] || "1") * 1000;
          setTimeout(() => api(method, path, body).then(resolve, reject), wait);
          return;
        }
        res.statusCode >= 200 && res.statusCode < 300 ? resolve(JSON.parse(d)) : reject(new Error(`HTTP ${res.statusCode}: ${d.slice(0, 200)}`));
      });
    });
    req.on("error", reject);
    if (data) req.write(data);
    req.end();
  });
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

// Aggressive normalizer — strips RE/FW, *EXT*, non-alphanumeric
function norm(s) {
  return (s || "").toLowerCase()
    .replace(/^(re|fw|fwd):\s*/gi, "")
    .replace(/^(re|fw|fwd):\s*/gi, "")
    .replace(/\*ext\*/gi, "")
    .replace(/[\u200b\ufeff]/g, "")
    .replace(/\s+/g, " ")
    .replace(/[^a-z0-9 ]/g, "")
    .trim()
    .slice(0, 100);
}

// Even more aggressive — first 40 chars only, for partial matches
function normShort(s) {
  return norm(s).slice(0, 40);
}

const SPAM = ["unsubscribe", "webinar", "save 30", "early bird", "holiday sale",
  "daily briefing", "networking", "cle credit", "seminar", "gift card",
  "referral partnership", "strategically invest", "mass tort", "stronger demand",
  "workflow costing", "free trial", "lien headaches", "ims insights", "dri ",
  "law.com", "bloomberg", "lexisnexis", "westlaw", "clio", "smokeball",
  "litify", "filevine calendar", "reauthentication",
  "pro bono", "your network", "region-0000 law con", "nashville seminar",
  "aaj ", "super bowl", "attorney self-evaluation"];

async function run() {
  if (!TOKEN) { console.error("NOTION_TOKEN not set"); process.exit(1); }
  if (!DB) { console.error("NOTION_ALL_EMAIL_DB not set"); process.exit(1); }

  console.log(`Loading ${EMAILS_JSON}...`);
  const csv = JSON.parse(readFileSync(EMAILS_JSON, "utf8"));
  const verified = csv.filter(e => e.dateShort && (e.dateSource === "body" || e.dateSource === "subject"));
  console.log(`  ${verified.length} verified-date emails in CSV`);

  // Build multi-tier lookup
  const exactLookup = new Map();
  const normLookup = new Map();
  const shortLookup = new Map();
  for (const e of verified) {
    const exact = (e.subject || "").toLowerCase().trim().slice(0, 120);
    const n = norm(e.subject);
    const s = normShort(e.subject);
    if (!exactLookup.has(exact)) exactLookup.set(exact, e);
    if (!normLookup.has(n)) normLookup.set(n, e);
    if (!shortLookup.has(s)) shortLookup.set(s, e);
  }
  console.log(`  Exact keys: ${exactLookup.size}, Norm keys: ${normLookup.size}, Short keys: ${shortLookup.size}`);

  // Fetch estimated-date pages
  console.log("Fetching estimated-date emails from Notion...");
  const pages = [];
  let cursor;
  while (true) {
    const body = { page_size: 100, filter: { property: "Date Confidence", select: { equals: "estimated" } } };
    if (cursor) body.start_cursor = cursor;
    const resp = await api("POST", `/v1/databases/${DB}/query`, body);
    pages.push(...resp.results);
    if (!resp.has_more) break;
    cursor = resp.next_cursor;
  }
  console.log(`  ${pages.length} estimated-date pages`);

  let fixedExact = 0, fixedNorm = 0, fixedShort = 0;
  let spam = 0, admin = 0, caseUnmatched = 0;
  let errors = 0;
  const total = fixedExact + fixedNorm + fixedShort;

  for (let i = 0; i < pages.length; i++) {
    const p = pages[i];
    const subj = p.properties.Subject?.title?.map(t => t.plain_text).join("") || "";
    const exact = subj.toLowerCase().trim().slice(0, 120);
    const n = norm(subj);
    const s = normShort(subj);

    let match = exactLookup.get(exact) || normLookup.get(n) || shortLookup.get(s);

    if (!match) {
      // Classify unmatched
      const lower = subj.toLowerCase();
      if (SPAM.some(k => lower.includes(k))) spam++;
      else if (lower.includes("v.") || lower.includes("vs") || lower.includes("claim") || lower.includes("cl #") || lower.includes("cl#")) caseUnmatched++;
      else admin++;
      continue;
    }

    const tier = exactLookup.has(exact) ? "exact" : normLookup.has(n) ? "norm" : "short";

    if (DRY_RUN) {
      if (tier === "exact") fixedExact++;
      else if (tier === "norm") fixedNorm++;
      else fixedShort++;
      continue;
    }

    try {
      await api("PATCH", `/v1/pages/${p.id}`, {
        properties: {
          Date: { date: { start: match.dateShort } },
          "Date Confidence": { select: { name: "extracted" } },
        },
      });
      if (tier === "exact") fixedExact++;
      else if (tier === "norm") fixedNorm++;
      else fixedShort++;
      const done = fixedExact + fixedNorm + fixedShort;
      if (done % 25 === 0) console.log(`  ${done} fixed (${i + 1}/${pages.length} scanned)...`);
      await sleep(350);
    } catch (e) {
      errors++;
      if (errors < 5) console.error(`  ERR: ${subj.slice(0, 50)} — ${e.message.slice(0, 100)}`);
    }
  }

  const fixed = fixedExact + fixedNorm + fixedShort;
  console.log(`\n=== DE-FUZZ RESULTS ${DRY_RUN ? "(DRY RUN)" : ""} ===`);
  console.log(`Fixed: ${fixed} (exact: ${fixedExact}, norm: ${fixedNorm}, short: ${fixedShort})`);
  console.log(`Unmatched: ${spam + admin + caseUnmatched}`);
  console.log(`  Spam/newsletters: ${spam}`);
  console.log(`  Admin/internal: ${admin}`);
  console.log(`  Case-related but no CSV match: ${caseUnmatched}`);
  console.log(`Errors: ${errors}`);
}

run().catch(e => { console.error(e); process.exit(1); });
