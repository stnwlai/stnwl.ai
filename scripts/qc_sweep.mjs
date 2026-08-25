/**
 * qc_sweep.mjs — Comprehensive QC sweep of Legal Matters Notion DB
 * Cross-checks Notion data against email corpus, case_index.json, and case_dates.json
 * Audit-only: flags inconsistencies but changes nothing.
 */

import { readFileSync } from 'fs';
import { resolve } from 'path';

// ── Config ──────────────────────────────────────────────────────────────────
const NOTION_TOKEN = process.env.NOTION_TOKEN || '';
const LEGAL_MATTERS_DB = process.env.NOTION_LEGAL_MATTERS_DB || 'YOUR_LEGAL_MATTERS_DATABASE_ID';
const TODAY = new Date();

const BASE = process.env.STONEWALL_BASE || new URL('..', import.meta.url).pathname.replace(/^\/([A-Z]:)/, '$1');
const CASE_INDEX_PATH = resolve(BASE, 'scripts/case_index.json');
const CASE_DATES_PATH = resolve(BASE, 'scripts/case_dates.json');
const EMAILS_PATH = resolve(BASE, 'reference_data/mail/consolidated_emails.json');

// ── Load local data ─────────────────────────────────────────────────────────
const caseIndex = JSON.parse(readFileSync(CASE_INDEX_PATH, 'utf8'));
const caseDates = JSON.parse(readFileSync(CASE_DATES_PATH, 'utf8'));
const emails = JSON.parse(readFileSync(EMAILS_PATH, 'utf8'));

// Build lookup maps keyed by Notion page ID (hyphenated)
function hyphenate(id) {
  const s = id.replace(/-/g, '');
  if (s.length !== 32) return id;
  return `${s.slice(0,8)}-${s.slice(8,12)}-${s.slice(12,16)}-${s.slice(16,20)}-${s.slice(20)}`;
}

const indexById = new Map();
for (const c of caseIndex) {
  if (c.id) indexById.set(hyphenate(c.id), c);
}
const indexByName = new Map();
for (const c of caseIndex) indexByName.set(c.name?.toLowerCase()?.trim(), c);

const datesById = new Map();
for (const c of caseDates) {
  if (c.id) datesById.set(hyphenate(c.id), c);
}
const datesByName = new Map();
for (const c of caseDates) datesByName.set(c.name?.toLowerCase()?.trim(), c);

// Build email index: claim number -> emails
const emailsByClaim = new Map();
for (const e of emails) {
  const subj = e.subject || '';
  // Extract carrier claim numbers from subject lines (letter-prefixed digit runs)
  const claims = subj.match(/[A-Z]{1,2}\d{8,10}/gi) || [];
  for (const cl of claims) {
    const key = cl.toUpperCase().replace(/-/g, '');
    if (!emailsByClaim.has(key)) emailsByClaim.set(key, []);
    emailsByClaim.get(key).push(e);
  }
}

// Also index by plaintiff last name for fuzzy matching
const emailsByPlaintiffName = new Map();
for (const e of emails) {
  const subj = (e.subject || '').toLowerCase();
  for (const c of caseIndex) {
    if (!c.plaintiff) continue;
    const lastName = c.plaintiff.split(/[\s,]+/)[c.plaintiff.includes(',') ? 0 : c.plaintiff.split(/\s+/).length - 1]?.toLowerCase();
    if (lastName && lastName.length > 3 && subj.includes(lastName)) {
      if (!emailsByPlaintiffName.has(c.name)) emailsByPlaintiffName.set(c.name, []);
      emailsByPlaintiffName.get(c.name).push(e);
    }
  }
}

// ── Notion API helpers ──────────────────────────────────────────────────────
async function notionFetch(path, body = null) {
  const opts = {
    method: body ? 'POST' : 'GET',
    headers: {
      'Authorization': `Bearer ${NOTION_TOKEN}`,
      'Notion-Version': '2022-06-28',
      'Content-Type': 'application/json',
    },
  };
  if (body) opts.body = JSON.stringify(body);
  const resp = await fetch(`https://api.notion.com/v1${path}`, opts);
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`Notion API ${resp.status}: ${text}`);
  }
  return resp.json();
}

async function fetchAllPages() {
  const pages = [];
  let cursor = undefined;
  while (true) {
    const body = { page_size: 100 };
    if (cursor) body.start_cursor = cursor;
    const result = await notionFetch(`/databases/${LEGAL_MATTERS_DB}/query`, body);
    pages.push(...result.results);
    if (!result.has_more) break;
    cursor = result.next_cursor;
  }
  return pages;
}

// ── Property extractors ─────────────────────────────────────────────────────
function extractProp(prop) {
  if (!prop) return { value: null, type: null };
  const t = prop.type;
  switch (t) {
    case 'title':
      return { value: prop.title?.map(r => r.plain_text).join('') || null, type: t };
    case 'rich_text':
      return { value: prop.rich_text?.map(r => r.plain_text).join('') || null, type: t };
    case 'number':
      return { value: prop.number, type: t };
    case 'select':
      return { value: prop.select?.name || null, type: t };
    case 'multi_select':
      return { value: prop.multi_select?.map(s => s.name) || [], type: t };
    case 'date':
      return { value: prop.date?.start || null, type: t };
    case 'checkbox':
      return { value: prop.checkbox, type: t };
    case 'url':
      return { value: prop.url || null, type: t };
    case 'email':
      return { value: prop.email || null, type: t };
    case 'phone_number':
      return { value: prop.phone_number || null, type: t };
    case 'formula':
      return { value: prop.formula?.[prop.formula?.type] ?? null, type: t };
    case 'rollup':
      return { value: prop.rollup?.[prop.rollup?.type] ?? null, type: t };
    case 'relation':
      return { value: prop.relation?.map(r => r.id) || [], type: t };
    case 'status':
      return { value: prop.status?.name || null, type: t };
    case 'people':
      return { value: prop.people?.map(p => p.name || p.id) || [], type: t };
    case 'files':
      return { value: prop.files?.map(f => f.name || f.external?.url) || [], type: t };
    case 'created_time':
      return { value: prop.created_time || null, type: t };
    case 'last_edited_time':
      return { value: prop.last_edited_time || null, type: t };
    default:
      return { value: JSON.stringify(prop), type: t };
  }
}

function isEmpty(val) {
  if (val === null || val === undefined) return true;
  if (typeof val === 'string' && val.trim() === '') return true;
  if (Array.isArray(val) && val.length === 0) return true;
  if (typeof val === 'boolean') return false;  // checkboxes are never "empty"
  return false;
}

// ── Normalization helpers ───────────────────────────────────────────────────
function normClaim(s) {
  if (!s) return '';
  return s.replace(/[\s\-]/g, '').toUpperCase();
}

function normName(s) {
  if (!s) return '';
  return s.toLowerCase().replace(/[^a-z]/g, ' ').replace(/\s+/g, ' ').trim();
}

function parseMoney(s) {
  if (!s) return null;
  const m = String(s).replace(/[$,\s]/g, '');
  const n = parseFloat(m);
  return isNaN(n) ? null : n;
}

function parseDate(s) {
  if (!s) return null;
  // Handle ISO dates and MM/DD/YYYY
  const d = new Date(s);
  if (isNaN(d.getTime())) return null;
  return d;
}

// ── QC Checks ───────────────────────────────────────────────────────────────
const flags = [];
function flag(caseName, field, currentVal, expectedVal, source, severity = 'FLAG') {
  flags.push({ caseName, field, currentVal: String(currentVal ?? '(empty)'), expectedVal: String(expectedVal ?? '(empty)'), source, severity });
}

// ── Main ────────────────────────────────────────────────────────────────────
async function main() {
  console.log('='.repeat(80));
  console.log('  LEGAL MATTERS DATABASE — COMPREHENSIVE QC SWEEP');
  console.log('  Date: 2026-03-26');
  console.log('='.repeat(80));
  console.log();

  // 1. Fetch all pages
  console.log('[1/4] Fetching all Legal Matters pages from Notion...');
  const pages = await fetchAllPages();
  console.log(`      Retrieved ${pages.length} pages.`);
  console.log();

  // 2. Parse all properties
  console.log('[2/4] Parsing properties and computing cell statistics...');
  const caseRecords = [];
  let totalFilled = 0;
  let totalEmpty = 0;
  const propNames = new Set();

  for (const page of pages) {
    const props = {};
    for (const [key, val] of Object.entries(page.properties)) {
      propNames.add(key);
      const extracted = extractProp(val);
      props[key] = extracted.value;
      if (isEmpty(extracted.value)) {
        totalEmpty++;
      } else {
        totalFilled++;
      }
    }
    caseRecords.push({
      id: page.id,
      url: page.url,
      name: props['Name'] || props['Case Name'] || props['Title'] || Object.values(props).find(v => typeof v === 'string' && v.includes(' v. ')) || '(unnamed)',
      props,
      raw: page.properties,
    });
  }

  const totalCells = totalFilled + totalEmpty;
  console.log(`      Total properties found: ${propNames.size} (${[...propNames].join(', ')})`);
  console.log(`      Total cells: ${totalCells} (${totalFilled} filled, ${totalEmpty} empty)`);
  console.log();

  // Discover which property is the "name/title"
  // Try to figure out property names used for key fields
  const sampleProps = caseRecords[0]?.props || {};
  console.log('      Sample case properties:');
  for (const [k, v] of Object.entries(sampleProps)) {
    if (!isEmpty(v)) console.log(`        ${k}: ${typeof v === 'object' ? JSON.stringify(v) : v}`);
  }
  console.log();

  // Build property name mapping (flexible)
  function findProp(rec, ...candidates) {
    for (const c of candidates) {
      for (const key of Object.keys(rec.props)) {
        if (key.toLowerCase().replace(/[\s_-]/g, '') === c.toLowerCase().replace(/[\s_-]/g, '')) {
          return { key, value: rec.props[key] };
        }
      }
    }
    return { key: null, value: null };
  }

  // 3. Cross-check each case
  console.log('[3/4] Running cross-checks...');
  console.log();

  const claimsSeen = new Map(); // claim -> [caseName...]

  for (const rec of caseRecords) {
    const caseName = typeof rec.name === 'string' ? rec.name : String(rec.name);

    // Extract key fields
    const claim = findProp(rec, 'Claim', 'Claim Number', 'ClaimNumber', 'Claim #').value;
    const plaintiff = findProp(rec, 'Plaintiff', 'Plaintiff Name', 'PlaintiffName').value;
    const driver = findProp(rec, 'Carrier Driver', 'Driver', 'Driver Name').value;
    const status = findProp(rec, 'Status', 'Case Status', 'CaseStatus').value;
    const phase = findProp(rec, 'Phase', 'Case Phase', 'CasePhase', 'Litigation Phase').value;
    const trialDate = findProp(rec, 'Trial Date', 'TrialDate', 'Trial').value;
    const mediationDate = findProp(rec, 'Mediation Date', 'MediationDate', 'Mediation').value;
    const dol = findProp(rec, 'Date of Loss', 'DateOfLoss', 'DOL', 'Loss Date').value;
    const reserve = findProp(rec, 'Reserve', 'Reserves').value;
    const incurred = findProp(rec, 'Incurred', 'Total Incurred').value;

    // ── Find matching records in case_index and case_dates ──
    const idxMatch = indexById.get(rec.id) || indexByName.get(caseName.toLowerCase().trim());
    const dtMatch = datesById.get(rec.id) || datesByName.get(caseName.toLowerCase().trim());

    // ── Check 1: Duplicate claim numbers ──
    if (claim && !isEmpty(claim)) {
      const nc = normClaim(claim);
      if (nc) {
        if (!claimsSeen.has(nc)) claimsSeen.set(nc, []);
        claimsSeen.get(nc).push(caseName);
      }
    }

    // ── Check 2: Blank Status ──
    if (isEmpty(status)) {
      flag(caseName, 'Status', status, '(should be set)', 'Notion completeness');
    }

    // ── Check 3: Blank Phase ──
    if (isEmpty(phase)) {
      flag(caseName, 'Phase', phase, '(should be set)', 'Notion completeness');
    }

    // ── Check 4: Active case with past trial date ──
    if (status && String(status).toLowerCase().includes('active')) {
      const td = parseDate(trialDate);
      if (td && td < TODAY) {
        flag(caseName, 'Trial Date (Active case, past trial)', trialDate, `Status=${status}, but trial was ${trialDate}`, 'Date logic', 'CRITICAL');
      }
    }

    // ── Check 5: Trial date before mediation date ──
    if (trialDate && mediationDate) {
      const td = parseDate(trialDate);
      const md = parseDate(mediationDate);
      if (td && md && td < md) {
        flag(caseName, 'Trial before Mediation', `Trial=${trialDate}, Mediation=${mediationDate}`, 'Trial should be after mediation', 'Date logic');
      }
    }

    // ── Check 6: Incurred > Reserve ──
    const reserveNum = parseMoney(reserve);
    const incurredNum = parseMoney(incurred);
    if (reserveNum !== null && incurredNum !== null && incurredNum > reserveNum) {
      const overagePercent = ((incurredNum - reserveNum) / reserveNum * 100).toFixed(1);
      flag(caseName, 'Incurred > Reserve', `Incurred=$${incurredNum.toLocaleString()} vs Reserve=$${reserveNum.toLocaleString()} (+${overagePercent}%)`, 'Reserve should >= Incurred', 'Reserve adequacy', 'WARN');
    }

    // ── Check 7: Cross-check claim number against case_index ──
    if (idxMatch && claim && !isEmpty(claim) && idxMatch.claim) {
      if (normClaim(claim) !== normClaim(idxMatch.claim)) {
        flag(caseName, 'Claim Number mismatch', claim, idxMatch.claim, 'case_index.json');
      }
    }

    // ── Check 8: Cross-check plaintiff against case_index ──
    if (idxMatch && plaintiff && !isEmpty(plaintiff) && idxMatch.plaintiff && !isEmpty(idxMatch.plaintiff)) {
      const notionPlaintiff = normName(plaintiff);
      const indexPlaintiff = normName(idxMatch.plaintiff);
      // Fuzzy: check if either contains the other's last name
      const notionWords = notionPlaintiff.split(' ');
      const indexWords = indexPlaintiff.split(' ');
      const lastNotion = notionWords[notionWords.length - 1];
      const lastIndex = indexWords[indexWords.length - 1];
      if (lastNotion.length > 2 && lastIndex.length > 2 && lastNotion !== lastIndex && !indexPlaintiff.includes(lastNotion) && !notionPlaintiff.includes(lastIndex)) {
        flag(caseName, 'Plaintiff name mismatch', plaintiff, idxMatch.plaintiff, 'case_index.json');
      }
    }

    // ── Check 9: Cross-check Carrier Driver against case_index ──
    if (idxMatch && driver && !isEmpty(driver) && idxMatch.carrier_driver && !isEmpty(idxMatch.carrier_driver)) {
      const notionDriver = normName(driver);
      const indexDriver = normName(idxMatch.carrier_driver);
      const driverWords = notionDriver.split(' ').filter(w => w.length > 2);
      const idxDriverWords = indexDriver.split(' ').filter(w => w.length > 2);
      // Check if at least one significant word overlaps
      const overlap = driverWords.some(w => idxDriverWords.includes(w));
      if (!overlap && driverWords.length > 0 && idxDriverWords.length > 0) {
        flag(caseName, 'Carrier Driver mismatch', driver, idxMatch.carrier_driver, 'case_index.json');
      }
    }

    // ── Check 10: Cross-check DOL against case_index ──
    if (idxMatch && dol && !isEmpty(dol) && idxMatch.date_of_loss && !isEmpty(idxMatch.date_of_loss)) {
      const notionDol = parseDate(dol);
      const indexDol = parseDate(idxMatch.date_of_loss);
      if (notionDol && indexDol && Math.abs(notionDol - indexDol) > 86400000) {
        flag(caseName, 'Date of Loss mismatch', dol, idxMatch.date_of_loss, 'case_index.json');
      }
    }

    // ── Check 11: Cross-check against case_dates (reserve/incurred) ──
    if (dtMatch) {
      const dtReserve = parseMoney(dtMatch.reserve);
      const dtIncurred = parseMoney(dtMatch.incurred);
      if (reserveNum !== null && dtReserve !== null && reserveNum !== dtReserve) {
        flag(caseName, 'Reserve mismatch vs case_dates', `Notion=$${reserveNum.toLocaleString()}`, `case_dates=$${dtReserve.toLocaleString()}`, 'case_dates.json');
      }
      if (incurredNum !== null && dtIncurred !== null && incurredNum !== dtIncurred) {
        flag(caseName, 'Incurred mismatch vs case_dates', `Notion=$${incurredNum.toLocaleString()}`, `case_dates=$${dtIncurred.toLocaleString()}`, 'case_dates.json');
      }
      // Check claim number in dates file
      if (claim && !isEmpty(claim) && dtMatch.claim && !isEmpty(dtMatch.claim)) {
        if (normClaim(claim) !== normClaim(dtMatch.claim)) {
          flag(caseName, 'Claim mismatch vs case_dates', claim, dtMatch.claim, 'case_dates.json');
        }
      }
    }

    // ── Check 12: Mediation date in past for Active case ──
    if (status && String(status).toLowerCase().includes('active')) {
      const md = parseDate(mediationDate);
      // Only flag if mediation is WAY in the past (more than 1 year) which seems suspicious
      // Actually, mediation in the past for active case is normal. Only flag if there's no trial date set.
      // Let's flag differently: active + past mediation + no trial date = potentially stale
    }

    // ── Check 13: case_index entry exists for Notion case? ──
    if (!idxMatch) {
      flag(caseName, 'No case_index match', '(not found in case_index.json)', 'Expected matching entry', 'case_index.json', 'INFO');
    }

    // ── Check 14: Plaintiff field data quality ──
    if (plaintiff && typeof plaintiff === 'string' && plaintiff.length > 200) {
      flag(caseName, 'Plaintiff field contains excess text', `${plaintiff.substring(0, 80)}...`, 'Should contain only plaintiff name', 'Data quality', 'CRITICAL');
    }
  }

  // ── Check duplicate claims across cases ──
  for (const [claimNum, cases] of claimsSeen) {
    if (cases.length > 1) {
      flag(cases.join(' / '), 'Duplicate claim number', claimNum, `Shared by ${cases.length} cases: ${cases.join(', ')}`, 'Duplicate detection', 'WARN');
    }
  }

  // Also check case_index for duplicates not in Notion
  const indexClaims = new Map();
  for (const c of caseIndex) {
    if (c.claim && c.claim.trim()) {
      const nc = normClaim(c.claim);
      if (!indexClaims.has(nc)) indexClaims.set(nc, []);
      indexClaims.get(nc).push(c.name);
    }
  }
  for (const [claimNum, cases] of indexClaims) {
    if (cases.length > 1) {
      // Check if this was already flagged from Notion
      const existing = flags.find(f => f.field === 'Duplicate claim number' && normClaim(f.currentVal) === claimNum);
      if (!existing) {
        flag(cases.join(' / '), 'Duplicate claim in case_index', claimNum, `Shared by: ${cases.join(', ')}`, 'case_index.json duplicate', 'WARN');
      }
    }
  }

  // ── Check case_index entries that have no Notion page ──
  for (const c of caseIndex) {
    const found = caseRecords.some(r => r.id === (c.id ? hyphenate(c.id) : '__none__'));
    if (c.id && !found) {
      // Try name match
      const nameMatch = caseRecords.some(r => {
        const rname = typeof r.name === 'string' ? r.name.toLowerCase() : '';
        return rname.includes(c.name.toLowerCase().split(' v.')[0].trim().split(' v ')[0].trim());
      });
      if (!nameMatch) {
        flag(c.name, 'case_index entry without Notion page match', c.id, 'Expected matching Notion page', 'Orphan detection', 'INFO');
      }
    }
  }

  // 4. Generate report
  console.log('[4/4] Generating QC report...');
  console.log();
  console.log('='.repeat(80));
  console.log('  QC REPORT — LEGAL MATTERS DATABASE');
  console.log('='.repeat(80));
  console.log();

  // Summary stats
  console.log('--- SUMMARY STATISTICS ---');
  console.log(`  Total Notion pages:     ${caseRecords.length}`);
  console.log(`  Properties per page:    ${propNames.size}`);
  console.log(`  Total cells:            ${totalCells}`);
  console.log(`  Filled cells:           ${totalFilled} (${(totalFilled/totalCells*100).toFixed(1)}%)`);
  console.log(`  Empty cells:            ${totalEmpty} (${(totalEmpty/totalCells*100).toFixed(1)}%)`);
  console.log(`  case_index entries:     ${caseIndex.length}`);
  console.log(`  case_dates entries:     ${caseDates.length}`);
  console.log(`  Email corpus size:      ${emails.length} emails`);
  console.log(`  Emails indexed by claim: ${emailsByClaim.size} unique claims`);
  console.log();

  // Property fill rates
  console.log('--- PROPERTY FILL RATES ---');
  const propFill = {};
  for (const pn of propNames) propFill[pn] = { filled: 0, empty: 0 };
  for (const rec of caseRecords) {
    for (const pn of propNames) {
      if (isEmpty(rec.props[pn])) propFill[pn].empty++;
      else propFill[pn].filled++;
    }
  }
  const sortedProps = [...propNames].sort((a, b) => {
    const rateA = propFill[a].filled / (propFill[a].filled + propFill[a].empty);
    const rateB = propFill[b].filled / (propFill[b].filled + propFill[b].empty);
    return rateB - rateA;
  });
  for (const pn of sortedProps) {
    const total = propFill[pn].filled + propFill[pn].empty;
    const pct = (propFill[pn].filled / total * 100).toFixed(0);
    const bar = '#'.repeat(Math.round(pct / 5)) + '.'.repeat(20 - Math.round(pct / 5));
    console.log(`  ${pn.padEnd(30)} ${propFill[pn].filled}/${total}  [${bar}] ${pct}%`);
  }
  console.log();

  // Per-case consistency check
  console.log('--- PER-CASE CONSISTENCY CHECK ---');
  const caseFlags = new Map();
  for (const f of flags) {
    if (!caseFlags.has(f.caseName)) caseFlags.set(f.caseName, []);
    caseFlags.get(f.caseName).push(f);
  }

  let passCount = 0;
  let flagCount = 0;
  for (const rec of caseRecords) {
    const caseName = typeof rec.name === 'string' ? rec.name : String(rec.name);
    const caseIssues = caseFlags.get(caseName) || [];
    // Also check flags where the case is part of a multi-case flag (duplicates)
    const additionalIssues = flags.filter(f => f.caseName.includes(caseName) && f.caseName !== caseName);
    const allIssues = [...caseIssues, ...additionalIssues];
    const hasCritical = allIssues.some(f => f.severity === 'CRITICAL');
    const hasWarn = allIssues.some(f => f.severity === 'WARN');
    const hasFlag = allIssues.some(f => f.severity === 'FLAG');

    if (allIssues.length === 0) {
      passCount++;
      console.log(`  [PASS] ${caseName}`);
    } else {
      flagCount++;
      const severity = hasCritical ? 'CRITICAL' : hasWarn ? 'WARN' : hasFlag ? 'FLAG' : 'INFO';
      console.log(`  [${severity}] ${caseName} — ${allIssues.length} issue(s)`);
    }
  }
  console.log();
  console.log(`  PASS: ${passCount}  |  FLAGGED: ${flagCount}`);
  console.log();

  // Detailed flag list
  console.log('--- FLAGGED ISSUES (DETAIL) ---');
  console.log();

  // Group by severity
  const bySeverity = { CRITICAL: [], WARN: [], FLAG: [], INFO: [] };
  for (const f of flags) {
    (bySeverity[f.severity] || bySeverity.FLAG).push(f);
  }

  for (const sev of ['CRITICAL', 'WARN', 'FLAG', 'INFO']) {
    const items = bySeverity[sev];
    if (items.length === 0) continue;
    console.log(`  [${ sev }] — ${items.length} issue(s)`);
    console.log('  ' + '-'.repeat(76));
    for (const f of items) {
      console.log(`  Case:     ${f.caseName}`);
      console.log(`  Field:    ${f.field}`);
      console.log(`  Current:  ${f.currentVal}`);
      console.log(`  Expected: ${f.expectedVal}`);
      console.log(`  Source:   ${f.source}`);
      console.log();
    }
  }

  // Duplicate claim summary
  console.log('--- DUPLICATE CLAIM NUMBERS ---');
  let dupCount = 0;
  for (const [claimNum, cases] of claimsSeen) {
    if (cases.length > 1) {
      dupCount++;
      console.log(`  ${claimNum} -> ${cases.join(', ')}`);
    }
  }
  for (const [claimNum, cases] of indexClaims) {
    if (cases.length > 1) {
      console.log(`  ${claimNum} (case_index) -> ${cases.join(', ')}`);
    }
  }
  if (dupCount === 0) console.log('  None found in Notion.');
  console.log();

  // Email coverage
  console.log('--- EMAIL COVERAGE CHECK ---');
  let emailHits = 0;
  let emailMisses = 0;
  for (const rec of caseRecords) {
    const claim = findProp(rec, 'Claim', 'Claim Number', 'ClaimNumber', 'Claim #').value;
    if (claim && !isEmpty(claim)) {
      const nc = normClaim(claim);
      const emailCount = emailsByClaim.get(nc)?.length || 0;
      if (emailCount > 0) {
        emailHits++;
      } else {
        emailMisses++;
        console.log(`  NO EMAILS FOUND: ${typeof rec.name === 'string' ? rec.name : ''} (claim: ${claim})`);
      }
    }
  }
  console.log(`  Cases with email matches: ${emailHits}`);
  console.log(`  Cases without email matches: ${emailMisses}`);
  console.log();

  console.log('='.repeat(80));
  console.log('  END OF QC REPORT');
  console.log(`  Total flags: ${flags.length} across ${flagCount} cases`);
  console.log('='.repeat(80));
}

main().catch(err => {
  console.error('FATAL ERROR:', err);
  process.exit(1);
});
