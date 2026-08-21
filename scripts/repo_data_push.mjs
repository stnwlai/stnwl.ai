#!/usr/bin/env node
/**
 * Repo Data Push — pushes case_index.json + case_dates.json directly
 * to Notion Legal Matters using stored page IDs. Fills only blank fields.
 */
import https from "https";
import { readFileSync } from "fs";
import { join, dirname } from "path";

const TOKEN = process.env.NOTION_TOKEN || "";
const DIR = dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Z]:)/, "$1"));
const ci = JSON.parse(readFileSync(join(DIR, "case_index.json"), "utf8"));
const cd = JSON.parse(readFileSync(join(DIR, "case_dates.json"), "utf8"));

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
          const w = parseFloat(res.headers["retry-after"] || "1.5") * 1000;
          setTimeout(() => api(method, path, body).then(resolve, reject), w);
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

function parseDate(val) {
  if (!val || !val.trim()) return null;
  let iso = val.trim();
  if (/^\d{4}-\d{2}-\d{2}/.test(iso)) return iso.slice(0, 10);
  const m = iso.match(/(\d{1,2})\/(\d{1,2})\/(\d{2,4})/);
  if (m) {
    let y = m[3]; if (y.length === 2) y = parseInt(y) > 50 ? "19" + y : "20" + y;
    return `${y}-${m[1].padStart(2, "0")}-${m[2].padStart(2, "0")}`;
  }
  return null;
}

async function run() {
  if (!TOKEN) { console.error("NOTION_TOKEN not set"); process.exit(1); }

  // Merge by page ID
  const merged = {};
  for (const c of ci) { if (c.id) merged[c.id.replace(/-/g, "")] = { ...c }; }
  for (const c of cd) { const id = (c.id || "").replace(/-/g, ""); if (id && merged[id]) Object.assign(merged[id], c); else if (id) merged[id] = c; }

  console.log(`${Object.keys(merged).length} cases to check`);
  let updated = 0, fills = 0, errors = 0, skipped = 0;

  for (const [pageId, c] of Object.entries(merged)) {
    if (pageId.length < 30) { skipped++; continue; }

    let page;
    try { page = await api("GET", `/v1/pages/${pageId}`); } catch { skipped++; continue; }
    const pr = page.properties;
    const updates = {};

    // Text fields
    const textMap = [
      ["Plaintiff", c.plaintiff],
      ["Carrier Driver", c.carrier_driver],
      ["Claim Number", c.claim],
      ["Case Number", c.case_number],
    ];
    for (const [field, val] of textMap) {
      if (!val?.trim()) continue;
      const cur = pr[field]?.rich_text?.map(t => t.plain_text).join("") || "";
      if (!cur.trim()) updates[field] = { rich_text: [{ text: { content: val.trim().slice(0, 2000) } }] };
    }

    // Date fields
    const dateMap = [
      ["Date of Loss", c.date_of_loss || c.dol],
      ["Date Complaint Filed", c.date_of_complaint || c.complaint_filed],
      ["Depo Date", c.depo_date],
      ["Discovery Date", c.disco_date],
    ];
    for (const [field, val] of dateMap) {
      const iso = parseDate(val);
      if (!iso) continue;
      if (pr[field]?.date?.start) continue;
      if (iso >= "2015-01-01" && iso <= "2030-01-01") {
        updates[field] = { date: { start: iso } };
      }
    }

    // Number fields
    const numMap = [
      ["Reserve", c.reserve],
      ["Incurred", c.incurred],
    ];
    for (const [field, val] of numMap) {
      if (!val) continue;
      const num = typeof val === "number" ? val : parseFloat(String(val).replace(/[,$]/g, ""));
      if (isNaN(num) || num <= 0) continue;
      if (pr[field]?.number != null) continue;
      updates[field] = { number: num };
    }

    if (Object.keys(updates).length === 0) continue;

    try {
      await api("PATCH", `/v1/pages/${pageId}`, { properties: updates });
      fills += Object.keys(updates).length;
      updated++;
      console.log(`  ${c.name}: ${Object.keys(updates).join(", ")}`);
      await sleep(400);
    } catch (e) {
      errors++;
      console.error(`  ERR: ${c.name} — ${e.message.slice(0, 100)}`);
    }
  }

  console.log(`\n=== REPO DATA PUSH ===`);
  console.log(`Cases updated: ${updated}`);
  console.log(`Cells filled: ${fills}`);
  console.log(`Skipped: ${skipped}`);
  console.log(`Errors: ${errors}`);
}

run().catch(e => { console.error(e); process.exit(1); });
