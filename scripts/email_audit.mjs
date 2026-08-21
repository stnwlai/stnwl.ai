#!/usr/bin/env node
/**
 * Email Audit & Auto-Tagger — Stonewall
 * Audits case tagging + date confidence, then auto-tags untagged emails.
 *
 * Usage:
 *   NOTION_TOKEN=ntn_xxx node scripts/email_audit.mjs --audit
 *   NOTION_TOKEN=ntn_xxx node scripts/email_audit.mjs --tag --limit 100
 *   NOTION_TOKEN=ntn_xxx node scripts/email_audit.mjs --fix-dates --limit 50
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
const FIX_DATES = args.has("--fix-dates");
let LIMIT = Infinity;
for (const a of args) {
  if (a.startsWith("--limit")) {
    const idx = process.argv.indexOf(a);
    LIMIT = parseInt(a.includes("=") ? a.split("=")[1] : process.argv[idx + 1]) || 100;
  }
}

function api(method, path, body) {
  return new Promise((resolve, reject) => {
    const data = body ? JSON.stringify(body) : null;
    const req = https.request({
      hostname: "api.notion.com", path, method,
      headers: {
        Authorization: `Bearer ${TOKEN}`,
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
        ...(data ? { "Content-Length": Buffer.byteLength(data) } : {}),
      },
    }, res => {
      let d = "";
      res.on("data", c => (d += c));
      res.on("end", () => {
        if (res.statusCode === 429) {
          const wait = parseFloat(res.headers["retry-after"] || "1") * 1000;
          setTimeout(() => api(method, path, body).then(resolve, reject), wait);
          return;
        }
        if (res.statusCode >= 200 && res.statusCode < 300) resolve(JSON.parse(d));
        else reject(new Error(`HTTP ${res.statusCode}: ${d.slice(0, 200)}`));
      });
    });
    req.on("error", reject);
    if (data) req.write(data);
    req.end();
  });
}

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

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

// Case keyword map: keyword -> Legal Matters page URL
const CASE_KEYWORDS = [
  { keys: ["matter 01", "driver alpha", "sample-001"], case: null },
  { keys: ["matter 02", "claimant beta", "sample-002"], case: null },
  { keys: ["matter 03", "facility gamma", "sample-003"], case: null },
  { keys: ["matter 04", "witness delta", "sample-004"], case: null },
  { keys: ["matter 05", "records epsilon", "sample-005"], case: null },
  { keys: ["matter 06", "coverage zeta", "sample-006"], case: null },
];

const SPAM_KEYWORDS = ["unsubscribe", "webinar", "save 30%", "early bird", "holiday sale",
  "daily briefing", "networking event", "cle credit", "seminar registration",
  "gift card", "referral partnership", "strategically invest", "mass tort",
  "stronger demand", "workflow costing", "free trial", "lien headaches",
  "ims insights", "dri ", "aaj ", "law.com", "bloomberg law"];

async function audit() {
  console.log("Fetching all emails...");
  const pages = await fetchAll(DB);
  console.log(`Total: ${pages.length}`);

  let noCase = 0, hasCase = 0, extracted = 0, estimated = 0;
  let caseRelatable = 0, spam = 0, admin = 0;
  const byCase = {};

  for (const p of pages) {
    const caseRel = p.properties["⚖️ Case"]?.relation;
    if (caseRel?.length > 0) hasCase++;
    else noCase++;

    const dc = p.properties["Date Confidence"]?.select?.name;
    if (dc === "extracted") extracted++;
    else if (dc === "estimated") estimated++;

    if (!caseRel?.length) {
      const subj = getTitle(p).toLowerCase();
      const from = getTextField(p, "From").toLowerCase();
      const to = getTextField(p, "To").toLowerCase();
      const text = subj + " " + from + " " + to;

      if (SPAM_KEYWORDS.some(k => text.includes(k))) { spam++; continue; }

      let matched = false;
      for (const entry of CASE_KEYWORDS) {
        if (entry.keys.some(k => text.includes(k))) {
          const label = entry.keys[0];
          byCase[label] = (byCase[label] || 0) + 1;
          caseRelatable++;
          matched = true;
          break;
        }
      }
      if (!matched) admin++;
    }
  }

  console.log("\n=== AUDIT RESULTS ===");
  console.log(`Tagged to case: ${hasCase} (${(hasCase / pages.length * 100).toFixed(1)}%)`);
  console.log(`NOT tagged: ${noCase} (${(noCase / pages.length * 100).toFixed(1)}%)`);
  console.log(`  Auto-taggable: ${caseRelatable}`);
  console.log(`  Spam/marketing: ${spam}`);
  console.log(`  Admin/internal: ${admin}`);
  console.log(`\nDate extracted: ${extracted} (${(extracted / pages.length * 100).toFixed(1)}%)`);
  console.log(`Date estimated: ${estimated} (${(estimated / pages.length * 100).toFixed(1)}%)`);
  console.log("\nAuto-taggable by case:");
  Object.entries(byCase).sort((a, b) => b[1] - a[1]).forEach(([c, n]) => console.log(`  ${c}: ${n}`));
}

async function autoTag() {
  console.log("Fetching Legal Matters for case page IDs...");
  const cases = await fetchAll(LEGAL_DB);
  const caseMap = {};
  for (const c of cases) {
    const name = getTitle(c).toLowerCase();
    caseMap[name] = c.id;
  }
  console.log(`  ${cases.length} cases loaded`);

  // Build keyword -> page ID mapping
  for (const entry of CASE_KEYWORDS) {
    const primary = entry.keys[0];
    for (const [name, id] of Object.entries(caseMap)) {
      if (entry.keys.some(k => name.includes(k))) {
        entry.case = id;
        break;
      }
    }
  }

  console.log("Fetching untagged emails...");
  const emails = await fetchAll(DB, { property: "\u2696\uFE0F Case", relation: { is_empty: true } });
  console.log(`  ${emails.length} untagged`);

  let tagged = 0, skipped = 0, errors = 0;
  for (const p of emails) {
    if (tagged >= LIMIT) { console.log(`Reached limit ${LIMIT}`); break; }

    const subj = getTitle(p).toLowerCase();
    const from = getTextField(p, "From").toLowerCase();
    const to = getTextField(p, "To").toLowerCase();
    const text = subj + " " + from + " " + to;

    let matchedCase = null;
    for (const entry of CASE_KEYWORDS) {
      if (entry.case && entry.keys.some(k => text.includes(k))) {
        matchedCase = entry.case;
        break;
      }
    }
    if (!matchedCase) { skipped++; continue; }

    try {
      await api("PATCH", `/v1/pages/${p.id}`, {
        properties: { "\u2696\uFE0F Case": { relation: [{ id: matchedCase }] } },
      });
      tagged++;
      if (tagged % 25 === 0) console.log(`  ${tagged} tagged...`);
      await sleep(350);
    } catch (e) {
      errors++;
      if (errors < 5) console.error(`  ERR: ${subj.slice(0, 50)} - ${e.message.slice(0, 100)}`);
    }
  }

  console.log(`\n=== TAG RESULTS ===`);
  console.log(`Tagged: ${tagged}`);
  console.log(`Skipped (no match): ${skipped}`);
  console.log(`Errors: ${errors}`);
}

async function fixDates() {
  console.log(`Loading ${EMAILS_JSON}...`);
  const csvEmails = JSON.parse(readFileSync(EMAILS_JSON, "utf8"));
  // dateSource "body" or "subject" = verified; "filename" = estimated
  const verified = csvEmails.filter(e => e.dateShort && (e.dateSource === "body" || e.dateSource === "subject"));
  console.log(`  ${verified.length} emails with verified dates (body/subject extraction)`);

  const lookup = new Map();
  for (const e of verified) {
    const key = (e.subject || "").toLowerCase().trim().slice(0, 120);
    if (!lookup.has(key)) lookup.set(key, e);
  }
  console.log(`  ${lookup.size} unique subject keys`);

  console.log("Fetching estimated-date emails from Notion...");
  const pages = await fetchAll(DB, {
    property: "Date Confidence",
    select: { equals: "estimated" },
  });
  console.log(`  ${pages.length} estimated-date emails`);

  let fixed = 0, noMatch = 0, errors = 0;
  for (const p of pages) {
    if (fixed >= LIMIT) { console.log(`Reached limit ${LIMIT}`); break; }

    const subj = getTitle(p).toLowerCase().trim().slice(0, 120);
    const csv = lookup.get(subj);
    if (!csv || !csv.dateShort) { noMatch++; continue; }

    try {
      await api("PATCH", `/v1/pages/${p.id}`, {
        properties: {
          Date: { date: { start: csv.dateShort } },
          "Date Confidence": { select: { name: "extracted" } },
        },
      });
      fixed++;
      if (fixed % 25 === 0) console.log(`  ${fixed} dates fixed...`);
      await sleep(350);
    } catch (e) {
      errors++;
      if (errors < 5) console.error(`  ERR: ${subj.slice(0, 50)} - ${e.message.slice(0, 100)}`);
    }
  }

  console.log(`\n=== DATE FIX RESULTS ===`);
  console.log(`Fixed: ${fixed}`);
  console.log(`No CSV match: ${noMatch}`);
  console.log(`Errors: ${errors}`);
}

async function run() {
  if (!TOKEN) { console.error("NOTION_TOKEN not set"); process.exit(1); }
  if (AUDIT) await audit();
  if (TAG) await autoTag();
  if (FIX_DATES) await fixDates();
  if (!AUDIT && !TAG && !FIX_DATES) {
    console.log("Usage: --audit | --tag [--limit N] | --fix-dates [--limit N]");
  }
}

run().catch(e => { console.error(e); process.exit(1); });
