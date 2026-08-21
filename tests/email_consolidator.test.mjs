import test from "node:test";
import assert from "node:assert/strict";

import {
  bestDate,
  dedupEmails,
  extractFilenameDateRange,
  parseCSV,
} from "../scripts/email_consolidator.mjs";

function makeEmail(overrides = {}) {
  return {
    subject: "Status update",
    from: "Legal Analyst",
    fromAddr: "analyst@example.com",
    to: "Client",
    toAddr: "client@example.com",
    cc: "",
    direction: "Sent",
    date: "2026-03-20T12:00:00+00:00",
    dateShort: "2026-03-20",
    dateConfidence: "estimated",
    dateSource: "filename",
    sourceFile: "sent 2026-03-18.csv",
    bodyDatesFound: 0,
    _bodyStart: "Hello re subpoena objections and next steps.",
    ...overrides,
  };
}

test("extractFilenameDateRange handles single-day, range, and long sent export names", () => {
  assert.deepEqual(extractFilenameDateRange("2.26.26 sent.csv"), {
    start: "2026-02-26",
    end: "2026-02-26",
  });
  assert.deepEqual(extractFilenameDateRange("sent 3.18.26-3.23.26.csv"), {
    start: "2026-03-18",
    end: "2026-03-23",
  });
  assert.deepEqual(extractFilenameDateRange("sent 1-3.21.26.csv"), {
    start: "2026-01-01",
    end: "2026-03-21",
  });
});

test("parseCSV preserves quoted commas, quotes, and embedded newlines", () => {
  const rows = parseCSV('Subject,Body\r\n"hello, world","Line 1\nLine ""2"""');
  assert.deepEqual(rows, [
    ["Subject", "Body"],
    ["hello, world", 'Line 1\nLine "2"'],
  ]);
});

test("bestDate ignores stale chain headers outside the export window", () => {
  const recent = new Date("2026-01-03T12:00:00Z");
  const stale = new Date("2025-11-20T12:00:00Z");
  const result = bestDate([stale, recent], [], {
    start: "2026-01-01",
    end: "2026-01-05",
  });

  assert.equal(result.confidence, "extracted");
  assert.equal(result.source, "body");
  assert.equal(result.date.toISOString().slice(0, 10), "2026-01-03");
});

test("dedupEmails keeps same-subject cross-source emails when the recipient changes", () => {
  const emails = [
    makeEmail({
      to: "Jordan",
      toAddr: "jordan@example.com",
      sourceFile: "sent 3.18.26-3.23.26.csv",
    }),
    makeEmail({
      to: "Client",
      toAddr: "casey@example.com",
      sourceFile: "sent 3.21.26 2.csv",
    }),
  ];

  const result = dedupEmails(emails);
  assert.equal(result.unique.length, 2);
  assert.equal(result.pass2Removed, 0);
});

test("dedupEmails merges overlapping exports for the same email and keeps the stronger date", () => {
  const emails = [
    makeEmail({
      sourceFile: "sent 3.18.26-3.23.26.csv",
      dateConfidence: "estimated",
      dateSource: "filename",
      _bodyStart: "Hello Jordan re subpoena objections and next steps.",
    }),
    makeEmail({
      sourceFile: "sent 3.21.26 2.csv",
      date: "2026-03-20T15:30:00+00:00",
      dateShort: "2026-03-20",
      dateConfidence: "extracted",
      dateSource: "body",
      _bodyStart: "Hello, Jordan - re subpoena objections and next steps!",
    }),
  ];

  const result = dedupEmails(emails);
  assert.equal(result.unique.length, 1);
  assert.equal(result.pass2Removed, 1);
  assert.equal(result.unique[0].dateConfidence, "extracted");
  assert.equal(result.unique[0].sourceFile, "sent 3.21.26 2.csv");
});
