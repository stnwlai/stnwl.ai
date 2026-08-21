import test from "node:test";
import assert from "node:assert/strict";

import {
  buildAnthropicHeaders,
  parseTransformResponse,
  roundTenth,
} from "../scripts/tracker_helpers.mjs";

test("parseTransformResponse extracts description, code, and minutes", () => {
  const parsed = parseTransformResponse(`Review and analyze deposition transcript
CODE: L330
MINS: 24`);
  assert.deepEqual(parsed, {
    desc: "Review and analyze deposition transcript",
    code: "L330",
    mins: 24,
  });
});

test("parseTransformResponse tolerates blank lines and invalid minutes", () => {
  const parsed = parseTransformResponse(`
Draft and revise motion outline

CODE: L170
MINS: TBD
`);
  assert.deepEqual(parsed, {
    desc: "Draft and revise motion outline",
    code: "L170",
    mins: null,
  });
});

test("roundTenth rounds to tenths with a minimum of 0.1", () => {
  assert.equal(roundTenth(1), 0.1);
  assert.equal(roundTenth(30), 0.5);
  assert.equal(roundTenth(95), 1.6);
});

test("buildAnthropicHeaders requires an API key", () => {
  assert.throws(() => buildAnthropicHeaders(), /Missing Anthropic API key/);
  assert.deepEqual(buildAnthropicHeaders("test-key"), {
    "Content-Type": "application/json",
    "x-api-key": "test-key",
    "anthropic-version": "2023-06-01",
  });
});
