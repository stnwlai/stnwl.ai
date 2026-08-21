#!/usr/bin/env node
/**
 * Email Deep Tagger — Stonewall
 * Aggressively tags emails to Legal Matters cases using expanded keyword matching
 * across subject, from, to, CC, AND body text from the consolidated JSON.
 *
 * Usage:
 *   NOTION_TOKEN=ntn_xxx node scripts/email_deep_tag.mjs --audit
 *   NOTION_TOKEN=ntn_xxx node scripts/email_deep_tag.mjs --tag
 *   NOTION_TOKEN=ntn_xxx node scripts/email_deep_tag.mjs --tag --dry-run
 */
import https from "https";
import { readFileSync } from "fs";
import { join, dirname } from "path";

const TOKEN = process.env.NOTION_TOKEN || "";
const DB = process.env.NOTION_ALL_EMAIL_DB || "YOUR_ALL_EMAIL_DATABASE_ID";
const LEGAL_DB = process.env.NOTION_LEGAL_MATTERS_DB || "YOUR_LEGAL_MATTERS_DATABASE_ID";
const EMAILS_JSON = join(dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Z]:)/, "$1")), "..", "sources", "emails", "consolidated_emails.json");

const args = new Set(process.argv.slice(2));
const AUDIT = args.has("--audit");
const TAG = args.has("--tag");
const DRY_RUN = args.has("--dry-run");

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

// EXPANDED case patterns — plaintiff, driver, OC, adjuster, claim variants
// Configure these with your firm's active matters.
// Each entry needs a display name and an array of lowercase keyword strings that
// identify emails belonging to that matter (plaintiff name, claim number, OC name, etc.)
const CASE_PATTERNS = [
  // Example entries — replace with your firm's actual matters:
  // { name: "Smith", keys: ["smith, john", "john smith", "cl12345ab", "cl12345-ab", "opposing-counsel-name", "adjuster-name"] },
  // { name: "Jones", keys: ["jones, jane", "jane jones", "cl67890cd", "cl67890-cd", "case-number"] },
];

// Spam patterns — emails that should NOT be tagged
const SPAM = ["unsubscribe", "webinar", "save 30", "early bird", "holiday sale",
  "daily briefing from", "networking event", "cle credit", "seminar registration",
  "gift card", "referral partnership", "strategically invest", "mass tort",
  "stronger demand letters", "workflow costing", "free trial", "lien headaches",
  "ims insights", "florida law con", "nashville seminar", "board elections",
  "bloomberg law", "lexisnexis weekly", "clio", "smokeball newsletter"];

async function fetchAll(dbId, filter) {
  const pages = [];
  let cursor;
  while (true) {
    const body = { page_size: 100, ...(filter ? { filter } : {}) };
    if (cursor) body.start_cursor = cursor;
    const resp = await api("POST", `/v1/databases/${dbId}/query`, body);
    pages.push(...resp.results);
    if (!resp.has_more) break;
    cursor = resp.next_cursor;
    if (pages.length % 500 === 0) process.stderr.write(`  ${pages.length} fetched...\n`);
  }
  return pages;
}

function getTitle(page) {
  for (const key of ["Subject", "\ufeffSubject", "Name", "Case Name"]) {
    const prop = page.properties?.[key];
    if (prop?.type === "title") return prop.title.map(t => t.plain_text).join("");
  }
  return "";
}

function getTextField(page, field) {
  const prop = page.properties?.[field];
  if (prop?.type === "rich_text") return prop.rich_text.map(t => t.plain_text).join("");
  return "";
}

function matchCase(text) {
  const lower = text.toLowerCase();
  if (SPAM.some(k => lower.includes(k))) return null;
  for (const entry of CASE_PATTERNS) {
    if (entry.keys.some(k => lower.includes(k))) return entry.name;
  }
  return null;
}

async function audit() {
  // Load CSV for body text
  console.log("Loading CSV emails for body text...");
  const csv = JSON.parse(readFileSync(EMAILS_JSON, "utf8"));
  const bodyLookup = new Map();
  for (const e of csv) {
    const key = (e.subject || "").toLowerCase().trim().slice(0, 120);
    if (!bodyLookup.has(key)) bodyLookup.set(key, e.body || "");
  }
  console.log(`  ${bodyLookup.size} body entries loaded`);

  console.log("Fetching untagged emails...");
  const pages = await fetchAll(DB, { property: "\u2696\uFE0F Case", relation: { is_empty: true } });
  console.log(`  ${pages.length} untagged`);

  let taggable = 0, spam = 0, noMatch = 0;
  const byCase = {};

  for (const p of pages) {
    const subj = getTitle(p);
    const from = getTextField(p, "From");
    const to = getTextField(p, "To");
    const cc = getTextField(p, "CC");
    const bodyKey = subj.toLowerCase().trim().slice(0, 120);
    const body = bodyLookup.get(bodyKey) || "";

    const fullText = `${subj} ${from} ${to} ${cc} ${body}`;
    const matched = matchCase(fullText);

    if (matched) {
      taggable++;
      byCase[matched] = (byCase[matched] || 0) + 1;
    } else if (SPAM.some(k => subj.toLowerCase().includes(k))) {
      spam++;
    } else {
      noMatch++;
    }
  }

  console.log(`\n=== DEEP TAG AUDIT ===`);
  console.log(`Taggable: ${taggable}`);
  console.log(`Spam: ${spam}`);
  console.log(`Unmatched: ${noMatch}`);
  console.log(`\nBy case:`);
  Object.entries(byCase).sort((a, b) => b[1] - a[1]).forEach(([c, n]) => console.log(`  ${c}: ${n}`));
}

async function tag() {
  // Load case page IDs
  console.log("Fetching Legal Matters...");
  const cases = await fetchAll(LEGAL_DB);
  const caseIdMap = {};
  for (const c of cases) {
    const name = getTitle(c).toLowerCase();
    caseIdMap[name] = c.id;
  }

  // Map CASE_PATTERNS to page IDs
  for (const entry of CASE_PATTERNS) {
    for (const [name, id] of Object.entries(caseIdMap)) {
      if (entry.keys.some(k => name.includes(k))) {
        entry.pageId = id;
        break;
      }
    }
  }

  const mapped = CASE_PATTERNS.filter(e => e.pageId).length;
  console.log(`  ${cases.length} cases, ${mapped} mapped to patterns`);

  // Load body text
  console.log("Loading CSV bodies...");
  const csv = JSON.parse(readFileSync(EMAILS_JSON, "utf8"));
  const bodyLookup = new Map();
  for (const e of csv) {
    const key = (e.subject || "").toLowerCase().trim().slice(0, 120);
    if (!bodyLookup.has(key)) bodyLookup.set(key, e.body || "");
  }

  console.log("Fetching untagged emails...");
  const pages = await fetchAll(DB, { property: "\u2696\uFE0F Case", relation: { is_empty: true } });
  console.log(`  ${pages.length} untagged`);

  let tagged = 0, skipped = 0, errors = 0;

  for (let i = 0; i < pages.length; i++) {
    const p = pages[i];
    const subj = getTitle(p);
    const from = getTextField(p, "From");
    const to = getTextField(p, "To");
    const cc = getTextField(p, "CC");
    const bodyKey = subj.toLowerCase().trim().slice(0, 120);
    const body = bodyLookup.get(bodyKey) || "";
    const fullText = `${subj} ${from} ${to} ${cc} ${body}`;
    const lower = fullText.toLowerCase();

    if (SPAM.some(k => lower.includes(k))) { skipped++; continue; }

    let matchedEntry = null;
    for (const entry of CASE_PATTERNS) {
      if (entry.pageId && entry.keys.some(k => lower.includes(k))) {
        matchedEntry = entry;
        break;
      }
    }

    if (!matchedEntry) { skipped++; continue; }

    if (DRY_RUN) {
      tagged++;
      if (tagged <= 10) console.log(`  [DRY] ${matchedEntry.name}: ${subj.slice(0, 60)}`);
      continue;
    }

    try {
      await api("PATCH", `/v1/pages/${p.id}`, {
        properties: { "\u2696\uFE0F Case": { relation: [{ id: matchedEntry.pageId }] } },
      });
      tagged++;
      if (tagged % 25 === 0) console.log(`  ${tagged} tagged (${i + 1}/${pages.length})...`);
      await sleep(350);
    } catch (e) {
      errors++;
      if (errors < 5) console.error(`  ERR: ${subj.slice(0, 50)} — ${e.message.slice(0, 100)}`);
    }
  }

  console.log(`\n=== DEEP TAG RESULTS ${DRY_RUN ? "(DRY RUN)" : ""} ===`);
  console.log(`Tagged: ${tagged}`);
  console.log(`Skipped: ${skipped}`);
  console.log(`Errors: ${errors}`);
}

async function run() {
  if (!TOKEN) { console.error("NOTION_TOKEN not set"); process.exit(1); }
  if (AUDIT) await audit();
  if (TAG) await tag();
  if (!AUDIT && !TAG) console.log("Usage: --audit | --tag [--dry-run]");
}

run().catch(e => { console.error(e); process.exit(1); });
