#!/usr/bin/env node
/**
 * Email Body Push — Stonewall
 * Reads consolidated_emails.json and pushes body text into Notion email pages.
 * Matches on subject+date, skips pages that already have content.
 *
 * Usage:
 *   NOTION_TOKEN=ntn_xxx node scripts/email_body_push.mjs
 *   NOTION_TOKEN=ntn_xxx node scripts/email_body_push.mjs --dry-run
 *   NOTION_TOKEN=ntn_xxx node scripts/email_body_push.mjs --limit 50
 */

import { readFileSync } from "fs";
import { join, dirname } from "path";
import https from "https";

const TOKEN = process.env.NOTION_TOKEN || "";
const DB_ID = process.env.NOTION_ALL_EMAIL_DB || "YOUR_ALL_EMAIL_DATABASE_ID";
const EMAILS_JSON = join(dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Z]:)/, "$1")), "..", "sources", "emails", "consolidated_emails.json");

const args = new Set(process.argv.slice(2));
const DRY_RUN = args.has("--dry-run");
let LIMIT = Infinity;
for (const a of args) {
  if (a.startsWith("--limit")) {
    const idx = process.argv.indexOf(a);
    LIMIT = parseInt(a.includes("=") ? a.split("=")[1] : process.argv[idx + 1]) || 50;
  }
}

function api(method, path, body) {
  return new Promise((resolve, reject) => {
    const data = body ? JSON.stringify(body) : null;
    const req = https.request({
      hostname: "api.notion.com",
      path,
      method,
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
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(JSON.parse(d));
        } else {
          reject(new Error(`HTTP ${res.statusCode}: ${d.slice(0, 200)}`));
        }
      });
    });
    req.on("error", reject);
    if (data) req.write(data);
    req.end();
  });
}

async function fetchAllPages() {
  console.log("Fetching Notion pages...");
  const pages = [];
  let cursor;
  while (true) {
    const body = { page_size: 100 };
    if (cursor) body.start_cursor = cursor;
    const resp = await api("POST", `/v1/databases/${DB_ID}/query`, body);
    pages.push(...resp.results);
    if (!resp.has_more) break;
    cursor = resp.next_cursor;
    if (pages.length % 500 === 0) console.log(`  ${pages.length} pages...`);
  }
  console.log(`  Total: ${pages.length} pages`);
  return pages;
}

function getSubject(page) {
  for (const key of ["Subject", "\ufeffSubject", "Name"]) {
    const prop = page.properties?.[key];
    if (prop?.type === "title") return prop.title.map(t => t.plain_text).join("");
  }
  return "";
}

function getDate(page) {
  const d = page.properties?.Date;
  return d?.type === "date" && d.date ? d.date.start.slice(0, 10) : "";
}

function matchKey(subject, date) {
  return `${(subject || "").toLowerCase().replace(/\u200b/g, "").trim().slice(0, 120)}|||${(date || "").slice(0, 10)}`;
}

async function hasContent(pageId) {
  const resp = await api("GET", `/v1/blocks/${pageId}/children?page_size=1`);
  return resp.results?.length > 0;
}

function textToBlocks(text, max = 1900) {
  if (!text?.trim()) return [];
  const blocks = [];
  for (const para of text.split("\n\n")) {
    const p = para.trim();
    if (!p) continue;
    for (let i = 0; i < p.length; i += max) {
      blocks.push({
        object: "block",
        type: "paragraph",
        paragraph: { rich_text: [{ type: "text", text: { content: p.slice(i, i + max) } }] },
      });
    }
  }
  return blocks;
}

async function appendBody(pageId, text) {
  const blocks = textToBlocks(text);
  if (!blocks.length) return false;
  for (let i = 0; i < blocks.length; i += 100) {
    await api("PATCH", `/v1/blocks/${pageId}/children`, { children: blocks.slice(i, i + 100) });
  }
  return true;
}

async function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

async function run() {
  if (!TOKEN) { console.error("ERROR: NOTION_TOKEN not set"); process.exit(1); }

  console.log(`Loading ${EMAILS_JSON}...`);
  const emails = JSON.parse(readFileSync(EMAILS_JSON, "utf8"));
  console.log(`  ${emails.length} emails loaded`);

  const withBody = emails.filter(e => e.body?.trim().length > 10);
  console.log(`  ${withBody.length} have body text`);

  const lookup = new Map();
  for (const e of withBody) {
    const key = matchKey(e.subject, e.dateShort || "");
    if (!lookup.has(key)) lookup.set(key, e);
  }
  console.log(`  ${lookup.size} unique subject+date keys`);

  const pages = await fetchAllPages();

  let matched = 0, updated = 0, skipped = 0, noBody = 0, errors = 0;

  for (let i = 0; i < pages.length; i++) {
    if (updated >= LIMIT) { console.log(`\n  Reached limit of ${LIMIT}`); break; }

    const page = pages[i];
    const subject = getSubject(page);
    const date = getDate(page);
    const key = matchKey(subject, date);
    const email = lookup.get(key);

    if (!email) { noBody++; continue; }
    matched++;

    try {
      if (await hasContent(page.id)) { skipped++; continue; }
    } catch { skipped++; continue; }

    if (DRY_RUN) {
      console.log(`  [DRY] ${subject.slice(0, 70)}`);
      updated++;
      continue;
    }

    try {
      await appendBody(page.id, email.body);
      updated++;
      if (updated % 10 === 0) console.log(`  ${updated} updated (${i + 1}/${pages.length} scanned)...`);
      await sleep(350); // rate limit buffer
    } catch (err) {
      errors++;
      console.error(`  ERR: ${subject.slice(0, 50)} — ${err.message.slice(0, 100)}`);
    }
  }

  console.log(`\n=== DONE ===`);
  console.log(`Pages scanned: ${pages.length}`);
  console.log(`Matched to CSV: ${matched}`);
  console.log(`Updated: ${updated}`);
  console.log(`Skipped (has content): ${skipped}`);
  console.log(`No body in CSV: ${noBody}`);
  console.log(`Errors: ${errors}`);
}

run().catch(err => { console.error(err); process.exit(1); });
