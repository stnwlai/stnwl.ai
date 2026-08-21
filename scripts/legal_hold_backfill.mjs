#!/usr/bin/env node
/**
 * Legal Hold Status Backfill
 * Sets Legal Hold Status on Legal Matters pages where it is currently blank.
 *
 * Rules:
 *   Active Hold    — cases with confirmed active holds (configure ACTIVE_HOLD array)
 *   Not Applicable — settled/closed cases (configure NOT_APPLICABLE array)
 *   Released       — cases with released holds (configure RELEASED array)
 *   Unknown        — all other active cases with blank status
 *
 * Usage:
 *   NOTION_TOKEN=ntn_xxx node scripts/legal_hold_backfill.mjs
 */
import https from "https";

const TOKEN = process.env.NOTION_TOKEN || "";
const LEGAL_DB = process.env.NOTION_LEGAL_MATTERS_DB || "YOUR_LEGAL_MATTERS_DATABASE_ID";

if (!TOKEN) { console.error("Missing NOTION_TOKEN"); process.exit(1); }

// ── Classification buckets (match on case name substrings) ──────────
// Populate these lists with the case names from your Legal Matters database.
const ACTIVE_HOLD = [];    // e.g., ["Smith v. Acme", "Jones v. Corp"]
const NOT_APPLICABLE = []; // e.g., ["Doe v. Widgets (settled)"]
const RELEASED = [];       // e.g., ["Brown v. LLC", "Green v. Inc"]

function classify(name) {
  if (ACTIVE_HOLD.some(k => name.includes(k))) return "Active Hold";
  if (NOT_APPLICABLE.some(k => name.includes(k))) return "Not Applicable";
  if (RELEASED.some(k => name.includes(k))) return "Released";
  return "Unknown";
}

// ── Notion API helper (raw https, rate-limit aware) ─────────────────
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
          console.log(`  Rate limited, waiting ${wait}ms...`);
          setTimeout(() => api(method, path, body).then(resolve, reject), wait);
          return;
        }
        if (res.statusCode >= 200 && res.statusCode < 300) resolve(JSON.parse(d));
        else reject(new Error(`HTTP ${res.statusCode}: ${d.slice(0, 300)}`));
      });
    });
    req.on("error", reject);
    if (data) req.write(data);
    req.end();
  });
}

// ── Fetch all pages from a database ─────────────────────────────────
async function fetchAll(dbId) {
  const pages = [];
  let cursor;
  while (true) {
    const body = { page_size: 100 };
    if (cursor) body.start_cursor = cursor;
    const resp = await api("POST", `/v1/databases/${dbId}/query`, body);
    pages.push(...resp.results);
    if (!resp.has_more) break;
    cursor = resp.next_cursor;
  }
  return pages;
}

// ── Extract title text from a Notion page ───────────────────────────
function getTitle(page) {
  for (const key of ["Name", "Case Name", "Title"]) {
    const prop = page.properties?.[key];
    if (prop?.type === "title") return prop.title.map(t => t.plain_text).join("");
  }
  return "(untitled)";
}

// ── Get current Legal Hold Status value ─────────────────────────────
function getHoldStatus(page) {
  const prop = page.properties?.["Legal Hold Status"];
  if (!prop || prop.type !== "select") return null;
  return prop.select?.name || null;
}

// ── Update a page's Legal Hold Status ───────────────────────────────
async function setHoldStatus(pageId, status) {
  return api("PATCH", `/v1/pages/${pageId}`, {
    properties: {
      "Legal Hold Status": {
        select: { name: status }
      }
    }
  });
}

// ── Main ────────────────────────────────────────────────────────────
async function main() {
  console.log("Fetching all Legal Matters pages...");
  const pages = await fetchAll(LEGAL_DB);
  console.log(`Fetched ${pages.length} pages total.\n`);

  // Find pages with blank Legal Hold Status
  const blanks = pages.filter(p => !getHoldStatus(p));
  console.log(`Found ${blanks.length} pages with blank Legal Hold Status.\n`);

  if (blanks.length === 0) {
    console.log("Nothing to update.");
    return;
  }

  // Classify and update each blank page
  let counts = { "Active Hold": 0, "Not Applicable": 0, "Released": 0, "Unknown": 0 };
  let errors = 0;

  for (const page of blanks) {
    const name = getTitle(page);
    const status = classify(name);
    try {
      await setHoldStatus(page.id, status);
      counts[status]++;
      console.log(`  [${status}] ${name}`);
    } catch (err) {
      errors++;
      console.error(`  ERROR updating "${name}": ${err.message}`);
    }
  }

  console.log(`\n--- Summary ---`);
  console.log(`Total updated: ${blanks.length - errors}`);
  for (const [k, v] of Object.entries(counts)) {
    if (v > 0) console.log(`  ${k}: ${v}`);
  }
  if (errors) console.log(`  Errors: ${errors}`);
  console.log("Done.");
}

main().catch(err => { console.error(err); process.exit(1); });
