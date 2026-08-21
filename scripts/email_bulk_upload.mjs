#!/usr/bin/env node
/**
 * Email Bulk Upload — Stonewall
 * Uploads ALL consolidated emails to the Notion All Email v2 database,
 * skipping duplicates that already exist (matched by subject+date).
 * Also sets case relations and pushes body text in one pass.
 *
 * Usage:
 *   NOTION_TOKEN=ntn_xxx node scripts/email_bulk_upload.mjs
 *   NOTION_TOKEN=ntn_xxx node scripts/email_bulk_upload.mjs --dry-run
 *   NOTION_TOKEN=ntn_xxx node scripts/email_bulk_upload.mjs --limit 500
 */
import https from "https";
import { readFileSync } from "fs";
import { join, dirname } from "path";

const TOKEN = process.env.NOTION_TOKEN || "";
const EMAIL_DB = process.env.NOTION_ALL_EMAIL_DB || "YOUR_ALL_EMAIL_DATABASE_ID";
const EMAIL_DS = process.env.NOTION_ALL_EMAIL_DS || "YOUR_ALL_EMAIL_DATASOURCE_ID";
const LEGAL_DB = process.env.NOTION_LEGAL_MATTERS_DB || "YOUR_LEGAL_MATTERS_DATABASE_ID";
const EMAILS_JSON = join(dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Z]:)/, "$1")), "..", "sources", "emails", "consolidated_emails.json");

const args = new Set(process.argv.slice(2));
const DRY_RUN = args.has("--dry-run");
let LIMIT = Infinity;
for (const a of args) {
  if (a.startsWith("--limit")) {
    const idx = process.argv.indexOf(a);
    LIMIT = parseInt(a.includes("=") ? a.split("=")[1] : process.argv[idx + 1]) || 500;
  }
}

function api(method, path, body, retries = 4) {
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
          const wait = parseFloat(res.headers["retry-after"] || "1.5") * 1000;
          setTimeout(() => api(method, path, body, retries).then(resolve, reject), wait);
          return;
        }
        if (res.statusCode === 409 || res.statusCode === 504) {
          if (retries > 0) { setTimeout(() => api(method, path, body, retries - 1).then(resolve, reject), 2000); return; }
        }
        res.statusCode >= 200 && res.statusCode < 300 ? resolve(JSON.parse(d)) : reject(new Error(`HTTP ${res.statusCode}: ${d.slice(0, 300)}`));
      });
    });
    req.on("error", e => { if (retries > 0) setTimeout(() => api(method, path, body, retries - 1).then(resolve, reject), 2000); else reject(e); });
    if (data) req.write(data);
    req.end();
  });
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

function matchKey(subject, date) {
  return `${(subject || "").toLowerCase().replace(/[\u200b\ufeff]/g, "").trim().slice(0, 120)}|||${(date || "").slice(0, 10)}`;
}

// Source file name → Source select option
function mapSource(sourceFile) {
  if (!sourceFile) return null;
  const f = sourceFile.toLowerCase();
  if (f.includes("dec 2025") && f.includes("inbox")) return "dec 2025 inbox";
  if (f.includes("dec 2025") && f.includes("sent")) return "dec 2025 sent";
  if (f.includes("1.1") && f.includes("inbox")) return "1.1-1.29 inbox";
  if (f.includes("1.1") && f.includes("sent")) return "1.1-1.29 sent";
  if (f.includes("2.11") && f.includes("sent")) return "2.11.26 sent";
  if (f.includes("2.19") && f.includes("inbox")) return "2.19.26 inbox";
  if (f.includes("2.19") && f.includes("sent")) return "2.19.26 sent";
  if (f.includes("2.26") && f.includes("inbox")) return "2.26.26 inbox";
  if (f.includes("2.26") && f.includes("sent")) return "2.26.26 sent";
  if (f.includes("3.17") && f.includes("sent")) return "3.17.26 sent";
  if (f.includes("3.11") && f.includes("3.18") && f.includes("inbox")) return "inbox 3.11-3.18";
  if (f.includes("3.11") && f.includes("3.18") && f.includes("sent")) return "sent 3.11-3.18";
  if (f.includes("3.18") && f.includes("3.23") && f.includes("inbox")) return "inbox 3.18-3.23";
  if (f.includes("3.18") && f.includes("3.23") && f.includes("sent")) return "sent 3.18-3.23";
  if (f.includes("3.21") && f.includes("inbox")) return "inbox 3.21.26 2";
  if (f.includes("3.21") && f.includes("sent")) return "sent 3.21.26 2";
  if (f.includes("sent 1-3")) return "sent 3.21.26 2";
  return null;
}

// Case matching patterns
// Configure these with your firm's active matters.
// Each entry needs a display name and an array of lowercase keyword strings that
// identify emails belonging to that matter (plaintiff name, claim number, OC name, etc.)
const CASE_PATTERNS = [
  // Example entries — replace with your firm's actual matters:
  // { name: "Smith", keys: ["smith, john", "john smith", "cl12345ab", "cl12345-ab", "opposing-counsel-name"] },
  // { name: "Jones", keys: ["jones, jane", "jane jones", "cl67890cd", "cl67890-cd"] },
];

function textToBlocks(text, max = 1900) {
  if (!text?.trim()) return [];
  const blocks = [];
  for (const para of text.split("\n\n")) {
    const p = para.trim();
    if (!p) continue;
    for (let i = 0; i < p.length; i += max) {
      blocks.push({
        object: "block", type: "paragraph",
        paragraph: { rich_text: [{ type: "text", text: { content: p.slice(i, i + max) } }] },
      });
    }
  }
  return blocks.slice(0, 95); // leave room under 100-block limit
}

async function run() {
  if (!TOKEN) { console.error("NOTION_TOKEN not set"); process.exit(1); }

  // Load emails
  console.log(`Loading ${EMAILS_JSON}...`);
  const emails = JSON.parse(readFileSync(EMAILS_JSON, "utf8"));
  console.log(`  ${emails.length} emails`);

  // Fetch existing pages to build dedup set
  console.log("Fetching existing Notion pages for dedup...");
  const existing = new Set();
  let cursor;
  let existCount = 0;
  while (true) {
    const body = { page_size: 100 };
    if (cursor) body.start_cursor = cursor;
    const resp = await api("POST", `/v1/databases/${EMAIL_DB}/query`, body);
    for (const p of resp.results) {
      const subj = p.properties.Subject?.title?.map(t => t.plain_text).join("") || "";
      const date = p.properties.Date?.date?.start?.slice(0, 10) || "";
      existing.add(matchKey(subj, date));
    }
    existCount += resp.results.length;
    if (!resp.has_more) break;
    cursor = resp.next_cursor;
    if (existCount % 500 === 0) console.log(`  ${existCount} existing pages indexed...`);
  }
  console.log(`  ${existing.size} unique existing entries`);

  // Load Legal Matters for case tagging
  console.log("Fetching Legal Matters for case tagging...");
  const casesResp = [];
  cursor = undefined;
  while (true) {
    const body = { page_size: 100 };
    if (cursor) body.start_cursor = cursor;
    const resp = await api("POST", `/v1/databases/${LEGAL_DB}/query`, body);
    casesResp.push(...resp.results);
    if (!resp.has_more) break;
    cursor = resp.next_cursor;
  }
  const caseIdMap = {};
  for (const c of casesResp) {
    const name = (c.properties["Case Name"]?.title?.map(t => t.plain_text).join("") || "").toLowerCase();
    caseIdMap[name] = c.id;
  }
  for (const entry of CASE_PATTERNS) {
    for (const [name, id] of Object.entries(caseIdMap)) {
      if (entry.keys.some(k => name.includes(k))) { entry.pageId = id; break; }
    }
  }
  console.log(`  ${casesResp.length} cases, ${CASE_PATTERNS.filter(e => e.pageId).length} mapped`);

  // Filter new emails
  const newEmails = emails.filter(e => !existing.has(matchKey(e.subject, e.dateShort)));
  console.log(`\nNew emails to upload: ${newEmails.length}`);
  console.log(`Skipping duplicates: ${emails.length - newEmails.length}`);

  let created = 0, errors = 0;

  for (const e of newEmails) {
    if (created >= LIMIT) { console.log(`Reached limit ${LIMIT}`); break; }

    // Build properties
    const props = {
      Subject: { title: [{ text: { content: (e.subject || "").slice(0, 2000) } }] },
      From: { rich_text: [{ text: { content: (e.from || "").slice(0, 2000) } }] },
      To: { rich_text: [{ text: { content: (e.to || "").slice(0, 2000) } }] },
      CC: { rich_text: [{ text: { content: (e.cc || "").slice(0, 2000) } }] },
      Direction: e.direction ? { select: { name: e.direction } } : undefined,
      "Date Confidence": { select: { name: e.dateSource === "body" || e.dateSource === "subject" ? "extracted" : "estimated" } },
    };

    if (e.dateShort) {
      props.Date = { date: { start: e.dateShort } };
    }

    const src = mapSource(e.sourceFile);
    if (src) props.Source = { select: { name: src } };

    // Case tagging
    const fullText = `${e.subject} ${e.from} ${e.to} ${e.cc} ${e.body || ""}`.toLowerCase();
    for (const entry of CASE_PATTERNS) {
      if (entry.pageId && entry.keys.some(k => fullText.includes(k))) {
        props["\u2696\uFE0F Case"] = { relation: [{ id: entry.pageId }] };
        break;
      }
    }

    // Clean undefined values
    for (const [k, v] of Object.entries(props)) { if (v === undefined) delete props[k]; }

    // Build body blocks
    const children = textToBlocks(e.body);

    if (DRY_RUN) {
      created++;
      if (created <= 5) console.log(`  [DRY] ${(e.subject || "").slice(0, 60)} | ${e.direction} | ${e.dateShort}`);
      continue;
    }

    try {
      const page = await api("POST", "/v1/pages", {
        parent: { database_id: EMAIL_DB },
        properties: props,
        ...(children.length ? { children } : {}),
      });
      created++;
      if (created % 50 === 0) console.log(`  ${created} created...`);
      await sleep(400);
    } catch (err) {
      errors++;
      if (errors <= 10) console.error(`  ERR ${errors}: ${(e.subject || "").slice(0, 50)} — ${err.message.slice(0, 150)}`);
      if (errors > 50) { console.error("Too many errors, aborting."); break; }
      await sleep(1000);
    }
  }

  console.log(`\n=== UPLOAD RESULTS ${DRY_RUN ? "(DRY RUN)" : ""} ===`);
  console.log(`Created: ${created}`);
  console.log(`Skipped (duplicate): ${emails.length - newEmails.length}`);
  console.log(`Errors: ${errors}`);
}

run().catch(e => { console.error(e); process.exit(1); });
