#!/usr/bin/env node
/**
 * Legal Matters Auto-Fill — Stonewall
 * Mines the full 5,526-email corpus to extract missing field values
 * for every Legal Matters case, then pushes updates to Notion.
 *
 * Usage:
 *   NOTION_TOKEN=ntn_xxx node scripts/legal_matters_fill.mjs --audit
 *   NOTION_TOKEN=ntn_xxx node scripts/legal_matters_fill.mjs --fill
 *   NOTION_TOKEN=ntn_xxx node scripts/legal_matters_fill.mjs --fill --dry-run
 */
import https from "https";
import { readFileSync } from "fs";
import { join, dirname } from "path";

const TOKEN = process.env.NOTION_TOKEN || "";
const LEGAL_DB = process.env.NOTION_LEGAL_MATTERS_DB || "YOUR_LEGAL_MATTERS_DATABASE_ID";
const EMAILS_JSON = join(dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Z]:)/, "$1")), "..", "sources", "emails", "consolidated_emails.json");
const CASE_INDEX = join(dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Z]:)/, "$1")), "case_index.json");
const CASE_DATES = join(dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Z]:)/, "$1")), "case_dates.json");

const args = new Set(process.argv.slice(2));
const AUDIT = args.has("--audit");
const FILL = args.has("--fill");
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
          const wait = parseFloat(res.headers["retry-after"] || "1.5") * 1000;
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

// Case keyword mapping for email matching
const CASE_EMAIL_KEYS = {
  "matter_01": ["matter 01", "driver alpha", "sample-001"],
  "matter_02": ["matter 02", "claimant beta", "sample-002"],
  "matter_03": ["matter 03", "facility gamma", "sample-003"],
  "matter_04": ["matter 04", "witness delta", "sample-004"],
  "matter_05": ["matter 05", "records epsilon", "sample-005"],
  "matter_06": ["matter 06", "coverage zeta", "sample-006"],
};

// Date extraction patterns
const DATE_PATTERNS = [
  /(\d{1,2})\/(\d{1,2})\/(\d{2,4})/g,  // M/D/YYYY or M/D/YY
  /(\d{4})-(\d{2})-(\d{2})/g,           // YYYY-MM-DD
  /(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2}),?\s*(\d{4})/gi,
];

const MONTH_MAP = { january: "01", february: "02", march: "03", april: "04", may: "05", june: "06",
  july: "07", august: "08", september: "09", october: "10", november: "11", december: "12" };

function extractDates(text) {
  const dates = [];
  // M/D/YYYY
  for (const m of text.matchAll(/(\d{1,2})\/(\d{1,2})\/(\d{2,4})/g)) {
    let y = m[3]; if (y.length === 2) y = parseInt(y) > 50 ? "19" + y : "20" + y;
    const mo = m[1].padStart(2, "0"), day = m[2].padStart(2, "0");
    if (parseInt(mo) <= 12 && parseInt(day) <= 31) dates.push({ date: `${y}-${mo}-${day}`, pos: m.index, context: text.slice(Math.max(0, m.index - 60), m.index + 30).toLowerCase() });
  }
  // Month DD, YYYY
  for (const m of text.matchAll(/(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2}),?\s*(\d{4})/gi)) {
    const mo = MONTH_MAP[m[0].split(/\s/)[0].toLowerCase()];
    const day = m[1].padStart(2, "0");
    dates.push({ date: `${m[2]}-${mo}-${day}`, pos: m.index, context: text.slice(Math.max(0, m.index - 60), m.index + 30).toLowerCase() });
  }
  return dates;
}

function classifyDate(context) {
  if (/trial|jury/i.test(context)) return "trial";
  if (/mediat|settlement\s*conf/i.test(context)) return "mediation";
  if (/discov|cutoff|close of/i.test(context)) return "discovery";
  if (/depo|transcript/i.test(context)) return "depo";
  if (/cme|compulsory|exam/i.test(context)) return "cme";
  if (/complaint\s*filed|filing\s*date|date\s*filed/i.test(context)) return "complaint_filed";
  if (/loss|accident|event|dol|crash|collision/i.test(context)) return "dol";
  if (/deadline|due|respond|response/i.test(context)) return "deadline";
  return null;
}

function extractDollar(text) {
  const amounts = [];
  for (const m of text.matchAll(/\$\s*([\d,]+(?:\.\d{2})?)/g)) {
    const val = parseFloat(m[1].replace(/,/g, ""));
    if (val > 100 && val < 50000000) amounts.push({ amount: val, context: text.slice(Math.max(0, m.index - 40), m.index + 30).toLowerCase() });
  }
  return amounts;
}

function classifyDollar(context) {
  if (/special|medical|med\s*bill|treatment|provider/i.test(context)) return "specials";
  if (/reserve/i.test(context)) return "reserve";
  if (/incur|billed|fees/i.test(context)) return "incurred";
  return null;
}

function extractCaseNumber(text) {
  // Florida case number patterns
  const patterns = [
    /(\d{2,4})-?CA-?(\d{4,8})/gi,
    /case\s*(?:no|number|#)[.:]*\s*(\d{2,4}CA\d{4,8}\w*)/gi,
    /(\d{2}:\d{2}-cv-\d{5})/gi,
  ];
  for (const p of patterns) {
    const m = p.exec(text);
    if (m) return m[0];
  }
  return null;
}

function extractClaimNumber(text) {
  const m = text.match(/(?:cl\s*#|claim\s*(?:no|number|#)[.:]*\s*)([A-Z]{1,3}\d[\d-]+)/i);
  return m ? m[1] : null;
}

async function run() {
  if (!TOKEN) { console.error("NOTION_TOKEN not set"); process.exit(1); }

  // Load data sources
  console.log("Loading email corpus...");
  const emails = JSON.parse(readFileSync(EMAILS_JSON, "utf8"));
  console.log(`  ${emails.length} emails`);

  let caseIndex = {}, caseDates = {};
  try { caseIndex = JSON.parse(readFileSync(CASE_INDEX, "utf8")); } catch {}
  try { caseDates = JSON.parse(readFileSync(CASE_DATES, "utf8")); } catch {}
  console.log(`  case_index: ${Object.keys(caseIndex).length} entries`);
  console.log(`  case_dates: ${Object.keys(caseDates).length} entries`);

  // Group emails by case
  console.log("Grouping emails by case...");
  const emailsByCase = {};
  for (const e of emails) {
    const text = `${e.subject || ""} ${e.from || ""} ${e.to || ""} ${e.cc || ""} ${e.body || ""}`.toLowerCase();
    for (const [caseName, keys] of Object.entries(CASE_EMAIL_KEYS)) {
      if (keys.some(k => text.includes(k))) {
        if (!emailsByCase[caseName]) emailsByCase[caseName] = [];
        emailsByCase[caseName].push(e);
        break;
      }
    }
  }
  const grouped = Object.entries(emailsByCase).map(([k, v]) => `${k}: ${v.length}`).join(", ");
  console.log(`  Grouped: ${Object.keys(emailsByCase).length} cases`);

  // Fetch Legal Matters
  console.log("Fetching Legal Matters...");
  const pages = []; let cursor;
  while (true) {
    const body = { page_size: 100 }; if (cursor) body.start_cursor = cursor;
    const resp = await api("POST", `/v1/databases/${LEGAL_DB}/query`, body);
    pages.push(...resp.results); if (!resp.has_more) break; cursor = resp.next_cursor;
  }
  console.log(`  ${pages.length} cases`);

  // For each case, mine emails and build fill plan
  const fills = [];
  let totalFills = 0;

  for (const page of pages) {
    const props = page.properties;
    const name = props["Case Name"]?.title?.map(t => t.plain_text).join("") || "?";
    const nameLower = name.toLowerCase();

    // Find matching case key
    let caseKey = null;
    for (const [k, keys] of Object.entries(CASE_EMAIL_KEYS)) {
      if (keys.some(kw => nameLower.includes(kw)) || nameLower.includes(k)) {
        caseKey = k;
        break;
      }
    }

    const caseEmails = caseKey ? (emailsByCase[caseKey] || []) : [];
    const allText = caseEmails.map(e => `${e.subject || ""}\n${e.body || ""}`).join("\n\n");

    // Check each field
    const updates = {};

    // TEXT FIELDS
    const textFields = [
      { field: "Plaintiff", prop: props.Plaintiff },
      { field: "Opposing Counsel", prop: props["Opposing Counsel"] },
      { field: "OC Firm", prop: props["OC Firm"] },
      { field: "Carrier Driver", prop: props["Carrier Driver"] },
      { field: "Adjuster", prop: props.Adjuster },
      { field: "Carrier Rep", prop: props["Carrier Rep"] },
      { field: "Claim Number", prop: props["Claim Number"] },
      { field: "Case Number", prop: props["Case Number"] },
      { field: "Injury Type", prop: props["Injury Type"] },
    ];

    for (const { field, prop } of textFields) {
      const val = prop?.rich_text?.map(t => t.plain_text).join("") || "";
      if (val.trim()) continue;

      let found = null;

      // Try case_index first
      if (caseKey) {
        const idx = Array.isArray(caseIndex) ? caseIndex.find(c => c.case_name?.toLowerCase().includes(caseKey)) : null;
        if (idx) {
          if (field === "Claim Number" && idx.claim_number) found = idx.claim_number;
          if (field === "Case Number" && idx.case_number) found = idx.case_number;
          if (field === "Plaintiff" && idx.plaintiff) found = idx.plaintiff;
          if (field === "Carrier Driver" && idx.carrier_driver) found = idx.carrier_driver;
        }
      }

      // Try email mining
      if (!found && caseEmails.length > 0) {
        if (field === "Case Number") found = extractCaseNumber(allText);
        if (field === "Claim Number") found = extractClaimNumber(allText);
        // OC/Adjuster from email From/To fields
        if (field === "Opposing Counsel" || field === "OC Firm") {
          // Look for external law firm emails
          for (const e of caseEmails) {
            const from = (e.from || "").toLowerCase();
            const fromAddr = (e.fromAddr || "").toLowerCase();
            if (fromAddr && !fromAddr.includes(process.env.FIRM_EMAIL_DOMAIN || "yourfirm") && !fromAddr.includes("filevine")) {
              if (fromAddr.includes("law") || fromAddr.includes("legal") || fromAddr.includes("esq") || fromAddr.includes("attorney")) {
                if (field === "Opposing Counsel" && !found) found = e.from;
                if (field === "OC Firm" && !found) {
                  const domain = fromAddr.split("@")[1];
                  if (domain) found = domain.replace(".com", "").replace("www.", "");
                }
              }
            }
          }
        }
      }

      if (found) {
        updates[field] = { rich_text: [{ text: { content: found.slice(0, 2000) } }] };
      }
    }

    // DATE FIELDS
    const dateFields = [
      { field: "Trial Date", prop: props["Trial Date"], types: ["trial"] },
      { field: "Mediation Date", prop: props["Mediation Date"], types: ["mediation"] },
      { field: "Discovery Date", prop: props["Discovery Date"], types: ["discovery"] },
      { field: "Depo Date", prop: props["Depo Date"], types: ["depo"] },
      { field: "Next Deadline", prop: props["Next Deadline"], types: ["deadline", "cme"] },
      { field: "Date of Loss", prop: props["Date of Loss"], types: ["dol"] },
      { field: "CME Deadline", prop: props["CME Deadline"], types: ["cme"] },
      { field: "Date Complaint Filed", prop: props["Date Complaint Filed"], types: ["complaint_filed"] },
    ];

    if (caseEmails.length > 0) {
      const allDates = extractDates(allText);

      for (const { field, prop, types } of dateFields) {
        if (prop?.date?.start) continue;

        // Try case_dates first
        if (caseKey) {
          const cd = Array.isArray(caseDates) ? caseDates.find(c => c.case_name?.toLowerCase().includes(caseKey)) : caseDates[caseKey];
          if (cd) {
            if (field === "Date of Loss" && cd.date_of_loss) { updates[`date:${field}:start`] = cd.date_of_loss; updates[`date:${field}:is_datetime`] = 0; continue; }
            if (field === "Depo Date" && cd.depo_date) { updates[`date:${field}:start`] = cd.depo_date; updates[`date:${field}:is_datetime`] = 0; continue; }
            if (field === "Discovery Date" && cd.discovery_date) { updates[`date:${field}:start`] = cd.discovery_date; updates[`date:${field}:is_datetime`] = 0; continue; }
          }
        }

        // Mine from emails
        const matching = allDates.filter(d => {
          const type = classifyDate(d.context);
          return type && types.includes(type);
        });

        if (matching.length > 0) {
          // Pick the most recent future date, or the latest date
          const now = "2026-03-26";
          const future = matching.filter(d => d.date >= now).sort((a, b) => a.date.localeCompare(b.date));
          const best = future[0] || matching.sort((a, b) => b.date.localeCompare(a.date))[0];
          if (best && best.date >= "2020-01-01" && best.date <= "2030-01-01") {
            updates[`date:${field}:start`] = best.date;
            updates[`date:${field}:is_datetime`] = 0;
          }
        }
      }
    }

    // FINANCIAL FIELDS
    const finFields = [
      { field: "Reserve", type: "reserve" },
      { field: "Incurred", type: "incurred" },
      { field: "Specials", type: "specials" },
    ];

    for (const { field, type } of finFields) {
      if (props[field]?.number != null) continue;

      // Try case_dates
      if (caseKey) {
        const cd = Array.isArray(caseDates) ? caseDates.find(c => c.case_name?.toLowerCase().includes(caseKey)) : caseDates[caseKey];
        if (cd) {
          if (field === "Reserve" && cd.reserve) { updates[field] = cd.reserve; continue; }
          if (field === "Incurred" && cd.incurred) { updates[field] = cd.incurred; continue; }
          if (field === "Specials" && cd.specials) { updates[field] = cd.specials; continue; }
        }
      }

      // Try email mining
      if (caseEmails.length > 0) {
        const amounts = extractDollar(allText);
        const matched = amounts.filter(a => classifyDollar(a.context) === type);
        if (matched.length > 0) {
          // Pick the largest for specials (cumulative), most recent mention otherwise
          const best = matched.sort((a, b) => b.amount - a.amount)[0];
          updates[field] = best.amount;
        }
      }
    }

    if (Object.keys(updates).length > 0) {
      fills.push({ name, pageId: page.id, updates });
      totalFills += Object.keys(updates).length;
    }
  }

  console.log(`\n=== FILL PLAN ===`);
  console.log(`Cases with fills: ${fills.length}`);
  console.log(`Total cells to fill: ${totalFills}`);
  console.log("");

  for (const f of fills) {
    const fields = Object.keys(f.updates).filter(k => !k.includes(":is_datetime")).join(", ");
    console.log(`  ${f.name}: ${fields}`);
  }

  if (!FILL) { console.log("\nRun with --fill to push updates."); return; }

  // Push updates
  let updated = 0, errors = 0;
  for (const f of fills) {
    const notionProps = {};

    for (const [key, val] of Object.entries(f.updates)) {
      if (key.startsWith("date:") && key.endsWith(":start")) {
        // Convert date:Field Name:start → proper Notion date format
        const fieldName = key.replace("date:", "").replace(":start", "");
        notionProps[fieldName] = { date: { start: val } };
      } else if (key.startsWith("date:") && key.endsWith(":is_datetime")) {
        // Skip — handled by the :start branch
        continue;
      } else if (typeof val === "number") {
        notionProps[key] = { number: val };
      } else if (typeof val === "object" && val.rich_text) {
        notionProps[key] = val;
      } else if (typeof val === "string") {
        notionProps[key] = { rich_text: [{ text: { content: val.slice(0, 2000) } }] };
      }
    }

    if (DRY_RUN) {
      updated++;
      continue;
    }

    try {
      await api("PATCH", `/v1/pages/${f.pageId}`, { properties: notionProps });
      updated++;
      if (updated % 10 === 0) console.log(`  ${updated} cases updated...`);
      await sleep(400);
    } catch (e) {
      errors++;
      console.error(`  ERR: ${f.name} — ${e.message.slice(0, 150)}`);
    }
  }

  console.log(`\n=== FILL RESULTS ${DRY_RUN ? "(DRY RUN)" : ""} ===`);
  console.log(`Updated: ${updated}`);
  console.log(`Errors: ${errors}`);
}

run().catch(e => { console.error(e); process.exit(1); });
