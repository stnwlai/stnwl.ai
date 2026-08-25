#!/usr/bin/env node
/**
 * Email Consolidator - Stonewall
 * ==========================================
 * Reads Outlook CSV email exports from reference_data/mail/,
 * extracts usable dates from the body/subject,
 * deduplicates overlapping exports,
 * and outputs consolidated data for Notion import.
 *
 * Usage:
 *   node scripts/email_consolidator.mjs
 *   node scripts/email_consolidator.mjs --json
 *   node scripts/email_consolidator.mjs --notion-csv
 */

import { readdirSync, readFileSync, writeFileSync } from "fs";
import { join, resolve } from "path";
import { fileURLToPath } from "url";

const EMAILS_DIR = join(import.meta.dirname, "..", "reference_data", "mail");
const DAY_MS = 24 * 60 * 60 * 1000;

export function discoverSources() {
  const files = readdirSync(EMAILS_DIR).filter(name => name.toLowerCase().endsWith(".csv"));
  return files.map(filename => {
    const lower = filename.toLowerCase();
    const direction = lower.includes("inbox")
      ? "Inbox"
      : lower.includes("sent")
        ? "Sent"
        : "Unknown";
    return {
      filename,
      path: join(EMAILS_DIR, filename),
      direction,
      dateRange: extractFilenameDateRange(filename),
    };
  });
}

export function extractFilenameDateRange(filename) {
  const lower = filename.toLowerCase().replace(/\.csv$/i, "");

  if (/sent\s+1-3\.21\.26/.test(lower)) {
    return { start: "2026-01-01", end: "2026-03-21" };
  }

  const rangeMatch = lower.match(
    /(\d{1,2})\.(\d{1,2})\.(\d{2,4})\s*(?:-|\u2013|to)\s*(\d{1,2})\.(\d{1,2})\.(\d{2,4})/,
  );
  if (rangeMatch) {
    return {
      start: toISO(rangeMatch[1], rangeMatch[2], rangeMatch[3]),
      end: toISO(rangeMatch[4], rangeMatch[5], rangeMatch[6]),
    };
  }

  const singleMatch = lower.match(/(\d{1,2})\.(\d{1,2})\.(\d{2,4})/);
  if (singleMatch) {
    const date = toISO(singleMatch[1], singleMatch[2], singleMatch[3]);
    return { start: date, end: date };
  }

  if (lower.includes("dec") && lower.includes("2025")) {
    return { start: "2025-12-01", end: "2025-12-31" };
  }
  if (lower.includes("jan") && lower.includes("2026")) {
    return { start: "2026-01-01", end: "2026-01-31" };
  }

  return { start: "2025-12-01", end: "2026-03-31" };
}

function toISO(month, day, year) {
  let normalizedYear = Number.parseInt(year, 10);
  if (normalizedYear < 100) {
    normalizedYear += 2000;
  }
  return `${normalizedYear}-${String(Number.parseInt(month, 10)).padStart(2, "0")}-${String(Number.parseInt(day, 10)).padStart(2, "0")}`;
}

export function parseCSV(text) {
  const rows = [];
  let index = 0;
  let row = [];
  let field = "";
  let inQuote = false;

  while (index < text.length) {
    const char = text[index];
    if (inQuote) {
      if (char === '"' && index + 1 < text.length && text[index + 1] === '"') {
        field += '"';
        index += 2;
        continue;
      }
      if (char === '"') {
        inQuote = false;
        index += 1;
        continue;
      }
      field += char;
      index += 1;
      continue;
    }

    if (char === '"') {
      inQuote = true;
      index += 1;
      continue;
    }
    if (char === ",") {
      row.push(field);
      field = "";
      index += 1;
      continue;
    }
    if (char === "\r" || char === "\n") {
      if (char === "\r" && index + 1 < text.length && text[index + 1] === "\n") {
        index += 1;
      }
      row.push(field);
      field = "";
      if (row.length > 1) {
        rows.push(row);
      }
      row = [];
      index += 1;
      continue;
    }
    field += char;
    index += 1;
  }

  if (row.length > 0 || field.length > 0) {
    row.push(field);
    if (row.length > 1) {
      rows.push(row);
    }
  }

  return rows;
}

const MONTHS = {
  january: 1,
  february: 2,
  march: 3,
  april: 4,
  may: 5,
  june: 6,
  july: 7,
  august: 8,
  september: 9,
  october: 10,
  november: 11,
  december: 12,
  jan: 1,
  feb: 2,
  mar: 3,
  apr: 4,
  jun: 6,
  jul: 7,
  aug: 8,
  sep: 9,
  oct: 10,
  nov: 11,
  dec: 12,
};

const SENT_RE = /Sent:\s*\w+day,?\s+(\w+)\s+(\d{1,2}),?\s+(\d{4})\s+(\d{1,2}):(\d{2})(?:\s*([AP]M))?/gi;
const ON_WROTE_RE = /On\s+\w+,?\s+(\w+)\s+(\d{1,2}),?\s+(\d{4})\s+at\s+(\d{1,2}):(\d{2})(?:\s*([AP]M))?/gi;
const DATE_HEADER_RE = /Date:\s*(\w+)\s+(\d{1,2}),?\s+(\d{4})(?:\s+(?:at\s+)?(\d{1,2}):(\d{2})(?:\s*([AP]M))?)?/gi;
const NUMERIC_TIME_RE = /(\d{1,2})\/(\d{1,2})\/(\d{4})\s+(\d{1,2}):(\d{2})(?:\s*([AP]M))?/gi;
const WHEN_RE = /When:\s*\w+day,?\s+(\w+)\s+(\d{1,2}),?\s+(\d{4})\s+(\d{1,2}):(\d{2})(?:\s*([AP]M))?/gi;
const WEEKDAY_DATE_RE = /(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+(\w+)\s+(\d{1,2}),?\s+(\d{4})/gi;
const NUMERIC_DATE_RE = /(\d{1,2})\/(\d{1,2})\/(\d{4})/gi;

function parseMonthDate(monthStr, dayStr, yearStr, hourStr, minuteStr, ampmStr) {
  const month = MONTHS[monthStr.toLowerCase()];
  if (!month) {
    return null;
  }

  const day = Number.parseInt(dayStr, 10);
  const year = Number.parseInt(yearStr, 10);
  let hour = hourStr ? Number.parseInt(hourStr, 10) : 12;
  const minute = minuteStr ? Number.parseInt(minuteStr, 10) : 0;
  const ampm = (ampmStr || "").toUpperCase();

  if (ampm === "PM" && hour < 12) {
    hour += 12;
  }
  if (ampm === "AM" && hour === 12) {
    hour = 0;
  }

  try {
    const parsed = new Date(year, month - 1, day, hour, minute);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
  } catch {
    return null;
  }
}

export function extractDatesFromBody(body) {
  if (!body) {
    return [];
  }

  const dates = [];

  for (const regex of [SENT_RE, ON_WROTE_RE, DATE_HEADER_RE, WHEN_RE]) {
    regex.lastIndex = 0;
    let match;
    while ((match = regex.exec(body)) !== null) {
      const parsed = parseMonthDate(match[1], match[2], match[3], match[4], match[5], match[6]);
      if (parsed) {
        dates.push(parsed);
      }
    }
  }

  NUMERIC_TIME_RE.lastIndex = 0;
  let numericMatch;
  while ((numericMatch = NUMERIC_TIME_RE.exec(body)) !== null) {
    const month = Number.parseInt(numericMatch[1], 10);
    const day = Number.parseInt(numericMatch[2], 10);
    const year = Number.parseInt(numericMatch[3], 10);
    let hour = Number.parseInt(numericMatch[4], 10);
    const minute = Number.parseInt(numericMatch[5], 10);
    const ampm = (numericMatch[6] || "").toUpperCase();

    if (ampm === "PM" && hour < 12) {
      hour += 12;
    }
    if (ampm === "AM" && hour === 12) {
      hour = 0;
    }

    if (month >= 1 && month <= 12 && day >= 1 && day <= 31) {
      try {
        const parsed = new Date(year, month - 1, day, hour, minute);
        if (!Number.isNaN(parsed.getTime())) {
          dates.push(parsed);
        }
      } catch {}
    }
  }

  if (dates.length === 0) {
    WEEKDAY_DATE_RE.lastIndex = 0;
    let weekdayMatch;
    while ((weekdayMatch = WEEKDAY_DATE_RE.exec(body)) !== null) {
      const parsed = parseMonthDate(weekdayMatch[1], weekdayMatch[2], weekdayMatch[3]);
      if (parsed) {
        dates.push(parsed);
      }
    }

    NUMERIC_DATE_RE.lastIndex = 0;
    let dateOnlyMatch;
    while ((dateOnlyMatch = NUMERIC_DATE_RE.exec(body)) !== null) {
      const month = Number.parseInt(dateOnlyMatch[1], 10);
      const day = Number.parseInt(dateOnlyMatch[2], 10);
      const year = Number.parseInt(dateOnlyMatch[3], 10);

      if (month >= 1 && month <= 12 && day >= 1 && day <= 31 && year >= 2025 && year <= 2026) {
        try {
          const parsed = new Date(year, month - 1, day, 12, 0);
          if (!Number.isNaN(parsed.getTime())) {
            dates.push(parsed);
          }
        } catch {}
      }
    }
  }

  dates.sort((left, right) => right.getTime() - left.getTime());
  return dates;
}

export function extractDatesFromSubject(subject) {
  if (!subject) {
    return [];
  }

  const dates = [];
  const monthDateRegex =
    /(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),?\s+(\d{4})/gi;
  let match;
  while ((match = monthDateRegex.exec(subject)) !== null) {
    const parsed = parseMonthDate(match[1], match[2], match[3]);
    if (parsed) {
      dates.push(parsed);
    }
  }

  const numericDateRegex = /(\d{1,2})\/(\d{1,2})\/(\d{2,4})/gi;
  while ((match = numericDateRegex.exec(subject)) !== null) {
    const month = Number.parseInt(match[1], 10);
    const day = Number.parseInt(match[2], 10);
    let year = Number.parseInt(match[3], 10);
    if (year < 100) {
      year += 2000;
    }
    if (month >= 1 && month <= 12 && day >= 1 && day <= 31 && year >= 2025 && year <= 2026) {
      try {
        const parsed = new Date(year, month - 1, day, 12, 0);
        if (!Number.isNaN(parsed.getTime())) {
          dates.push(parsed);
        }
      } catch {}
    }
  }

  return dates;
}

export function bestDate(bodyDates, subjectDates, fileRange) {
  if (fileRange?.start) {
    const rangeStart = new Date(`${fileRange.start}T00:00:00`);
    const rangeEnd = new Date(`${fileRange.end || fileRange.start}T23:59:59`);
    const windowStart = new Date(rangeStart.getTime() - 7 * DAY_MS);
    const windowEnd = new Date(rangeEnd.getTime() + 7 * DAY_MS);

    const bodyInWindow = bodyDates
      .filter(date => date >= windowStart && date <= windowEnd)
      .sort((left, right) => right.getTime() - left.getTime());
    if (bodyInWindow.length > 0) {
      return { date: bodyInWindow[0], confidence: "extracted", source: "body" };
    }

    const subjectInWindow = subjectDates
      .filter(date => date >= windowStart && date <= windowEnd)
      .sort((left, right) => right.getTime() - left.getTime());
    if (subjectInWindow.length > 0) {
      return { date: subjectInWindow[0], confidence: "extracted", source: "subject" };
    }

    return { date: rangeStart, confidence: "estimated", source: "filename" };
  }

  const absoluteMin = new Date(2025, 10, 1);
  const absoluteMax = new Date(2026, 3, 30);
  const allDates = [...bodyDates, ...subjectDates]
    .filter(date => date >= absoluteMin && date <= absoluteMax)
    .sort((left, right) => right.getTime() - left.getTime());

  if (allDates.length > 0) {
    return { date: allDates[0], confidence: "extracted", source: "body" };
  }

  return { date: null, confidence: "none", source: "none" };
}

function formatISO(date) {
  if (!date) {
    return null;
  }
  return date.toISOString().replace("Z", "+00:00").replace(/\.\d{3}/, "");
}

function formatDate(date) {
  if (!date) {
    return "";
  }
  return date.toISOString().slice(0, 10);
}

function normalizeKeyPart(value, limit = 120) {
  return String(value || "")
    .toLowerCase()
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, limit);
}

function bodyFingerprint(bodyStart, limit = 120) {
  return String(bodyStart || "")
    .toLowerCase()
    .replace(/\s+/g, "")
    .slice(0, limit);
}

function looseBodyFingerprint(bodyStart, limit = 120) {
  return String(bodyStart || "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim()
    .slice(0, limit);
}

function senderKey(email) {
  return normalizeKeyPart(email.fromAddr || email.from, 160);
}

function recipientKey(email) {
  return normalizeKeyPart(email.toAddr || email.to, 160);
}

function strictDedupKey(email) {
  return [
    normalizeKeyPart(email.subject, 160),
    senderKey(email),
    recipientKey(email),
    bodyFingerprint(email._bodyStart, 120),
  ].join("|||");
}

function crossSourceBucketKey(email) {
  return [
    normalizeKeyPart(email.subject, 160),
    senderKey(email),
    recipientKey(email),
    email.direction,
  ].join("|||");
}

function dateQualityScore(email) {
  const confidenceScore =
    email.dateConfidence === "extracted"
      ? 20
      : email.dateConfidence === "estimated"
        ? 10
        : 0;
  const sourceScore =
    email.dateSource === "body"
      ? 3
      : email.dateSource === "subject"
        ? 2
        : email.dateSource === "filename"
          ? 1
          : 0;
  return confidenceScore + sourceScore;
}

function preferEmail(existing, candidate) {
  const existingScore = dateQualityScore(existing);
  const candidateScore = dateQualityScore(candidate);
  if (candidateScore > existingScore) {
    return candidate;
  }
  if (candidateScore < existingScore) {
    return existing;
  }
  if ((candidate._bodyStart || "").length > (existing._bodyStart || "").length) {
    return candidate;
  }
  return existing;
}

function sameOrAdjacentDay(leftDate, rightDate) {
  if (!leftDate || !rightDate) {
    return true;
  }
  const left = new Date(`${leftDate}T00:00:00Z`);
  const right = new Date(`${rightDate}T00:00:00Z`);
  return Math.abs(left.getTime() - right.getTime()) <= DAY_MS;
}

function shouldMergeCrossSource(existing, candidate) {
  if (existing.sourceFile === candidate.sourceFile) {
    return false;
  }
  if (!sameOrAdjacentDay(existing.dateShort, candidate.dateShort)) {
    return false;
  }

  const existingBody = looseBodyFingerprint(existing._bodyStart, 160);
  const candidateBody = looseBodyFingerprint(candidate._bodyStart, 160);
  if (existingBody && candidateBody && existingBody !== candidateBody) {
    return false;
  }

  return true;
}

export function dedupEmails(allEmails) {
  const firstPass = new Map();
  for (const email of allEmails) {
    const key = strictDedupKey(email);
    const existing = firstPass.get(key);
    firstPass.set(key, existing ? preferEmail(existing, email) : email);
  }

  const pass1Unique = [...firstPass.values()];
  const pass1Removed = allEmails.length - pass1Unique.length;

  const buckets = new Map();
  let pass2Removed = 0;
  for (const email of pass1Unique) {
    const bucketKey = crossSourceBucketKey(email);
    const bucket = buckets.get(bucketKey) || [];
    const duplicateIndex = bucket.findIndex(existing => shouldMergeCrossSource(existing, email));

    if (duplicateIndex >= 0) {
      bucket[duplicateIndex] = preferEmail(bucket[duplicateIndex], email);
      pass2Removed += 1;
    } else {
      bucket.push(email);
    }

    buckets.set(bucketKey, bucket);
  }

  const unique = [...buckets.values()].flat();
  return { unique, pass1Removed, pass2Removed };
}

export function csvEscape(value) {
  if (!value) {
    return "";
  }
  if (value.includes(",") || value.includes('"') || value.includes("\n")) {
    return `"${value.replace(/"/g, '""')}"`;
  }
  return value;
}

export function run(argv = process.argv.slice(2)) {
  const outputJson = argv.includes("--json");
  const outputCsv = argv.includes("--notion-csv");

  console.log("=== EMAIL CONSOLIDATOR - Stonewall ===\n");

  const sources = discoverSources();
  console.log(`Found ${sources.length} CSV files in reference_data/mail/:\n`);
  for (const source of sources) {
    console.log(
      `  ${source.direction.padEnd(6)} ${source.dateRange.start} -> ${source.dateRange.end}  ${source.filename}`,
    );
  }
  console.log("");

  const allEmails = [];
  const stats = {
    totalParsed: 0,
    bySource: {},
    dateStats: { extracted: 0, estimated: 0, none: 0 },
  };

  for (const source of sources) {
    console.log(`Parsing ${source.filename}...`);
    let text;
    try {
      text = readFileSync(source.path, "utf8");
    } catch (error) {
      console.log(`  ERROR reading: ${error.message}`);
      continue;
    }

    if (text.charCodeAt(0) === 0xfeff) {
      text = text.slice(1);
    }

    const rows = parseCSV(text);
    if (rows.length < 2) {
      console.log("  No data rows found");
      continue;
    }

    const headers = rows[0].map(header => header.trim());
    const columnIndex = name => {
      const index = headers.findIndex(header => header === name || header === `\uFEFF${name}`);
      return index >= 0 ? index : -1;
    };

    const iSubject = columnIndex("Subject");
    const iBody = columnIndex("Body");
    const iFromName = columnIndex("From: (Name)");
    const iFromAddr = columnIndex("From: (Address)");
    const iToName = columnIndex("To: (Name)");
    const iToAddr = columnIndex("To: (Address)");
    const iCCName = columnIndex("CC: (Name)");

    let parsed = 0;
    for (let rowIndex = 1; rowIndex < rows.length; rowIndex += 1) {
      const row = rows[rowIndex];
      if (row.length < 5) {
        continue;
      }

      const subject = (iSubject >= 0 ? row[iSubject] : "") || "";
      const body = (iBody >= 0 ? row[iBody] : "") || "";
      const fromName = (iFromName >= 0 ? row[iFromName] : "") || "";
      const fromAddr = (iFromAddr >= 0 ? row[iFromAddr] : "") || "";
      const toName = (iToName >= 0 ? row[iToName] : "") || "";
      const toAddr = (iToAddr >= 0 ? row[iToAddr] : "") || "";
      const ccName = (iCCName >= 0 ? row[iCCName] : "") || "";

      const bodyDates = extractDatesFromBody(body);
      const subjectDates = extractDatesFromSubject(subject);
      const dateInfo = bestDate(bodyDates, subjectDates, source.dateRange);

      allEmails.push({
        subject: subject.slice(0, 2000),
        body: (body || '').toString().slice(0, 50000),
        from: fromName.slice(0, 500),
        fromAddr: fromAddr.slice(0, 200),
        to: toName.slice(0, 500),
        toAddr: toAddr.slice(0, 200),
        cc: ccName.slice(0, 500),
        direction: source.direction,
        date: formatISO(dateInfo.date),
        dateShort: formatDate(dateInfo.date),
        dateConfidence: dateInfo.confidence,
        dateSource: dateInfo.source,
        sourceFile: source.filename,
        bodyDatesFound: bodyDates.length,
        _bodyStart: body.replace(/^[\s\r\n]+/, "").slice(0, 200),
      });
      parsed += 1;
    }

    stats.totalParsed += parsed;
    stats.bySource[source.filename] = parsed;
    console.log(`  ${parsed} emails parsed`);
  }

  console.log(`\nTotal parsed: ${stats.totalParsed}`);
  console.log("\nDeduplicating...");

  const { unique, pass1Removed, pass2Removed } = dedupEmails(allEmails);
  const pass1UniqueCount = allEmails.length - pass1Removed;
  console.log(`Pass 1 (strict body fingerprint): ${pass1UniqueCount} unique (removed ${pass1Removed})`);
  console.log(`Pass 2 (cross-source dedup): ${unique.length} unique (removed ${pass2Removed} cross-source dupes)`);

  for (const email of unique) {
    stats.dateStats[email.dateConfidence] = (stats.dateStats[email.dateConfidence] || 0) + 1;
  }

  console.log("\nDate extraction:");
  console.log(`  Extracted from body/subject: ${stats.dateStats.extracted || 0}`);
  console.log(`  Estimated from filename: ${stats.dateStats.estimated || 0}`);
  console.log(`  No date: ${stats.dateStats.none || 0}`);

  const sent = unique.filter(email => email.direction === "Sent").length;
  const inbox = unique.filter(email => email.direction === "Inbox").length;
  console.log(`\nDirection: ${sent} sent, ${inbox} inbox`);

  const withDates = unique
    .filter(email => email.date)
    .sort((left, right) => left.date.localeCompare(right.date));
  if (withDates.length > 0) {
    console.log(`Date range: ${withDates[0].dateShort} -> ${withDates[withDates.length - 1].dateShort}`);
  }

  const byMonth = {};
  for (const email of unique) {
    const month = email.dateShort ? email.dateShort.slice(0, 7) : "unknown";
    byMonth[month] = (byMonth[month] || 0) + 1;
  }
  console.log("\nMonthly breakdown:");
  for (const [month, count] of Object.entries(byMonth).sort()) {
    console.log(`  ${month}: ${count}`);
  }

  const casePattern = /\b(v\.|v\s)/i;
  const caseEmails = unique.filter(email => casePattern.test(email.subject));
  console.log(`\nEmails with case references (v./v ): ${caseEmails.length}`);

  if (outputJson) {
    const outPath = join(import.meta.dirname, "..", "reference_data", "mail", "consolidated_emails.json");
    const exportData = [...unique]
      .sort((left, right) => (left.date || "").localeCompare(right.date || ""))
      .map(({ _bodyStart, ...rest }) => rest);
    writeFileSync(outPath, JSON.stringify(exportData, null, 2));
    console.log(`\nWrote ${exportData.length} emails to ${outPath}`);
  }

  if (outputCsv) {
    const outPath = join(import.meta.dirname, "..", "reference_data", "mail", "consolidated_emails.csv");
    const rows = [...unique]
      .sort((left, right) => (left.date || "").localeCompare(right.date || ""))
      .map(email =>
        [
          csvEscape(email.subject),
          csvEscape(email.from),
          csvEscape(email.fromAddr),
          csvEscape(email.to),
          csvEscape(email.cc),
          email.date || "",
          email.direction,
          email.dateConfidence,
          email.sourceFile,
        ].join(","),
      );
    writeFileSync(
      outPath,
      [["Subject", "From", "From Address", "To", "CC", "Date", "Direction", "Date Confidence", "Source File"].join(","), ...rows].join("\n"),
    );
    console.log(`\nWrote ${unique.length} emails to ${outPath}`);
  }

  console.log("\n=== CONSOLIDATION COMPLETE ===");
  return unique;
}

const isDirectRun =
  Boolean(process.argv[1]) &&
  resolve(process.argv[1]) === resolve(fileURLToPath(import.meta.url));

if (isDirectRun) {
  run();
}
