export const ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages";
export const ANTHROPIC_VERSION = "2023-06-01";

export function today() {
  return new Date().toISOString().split("T")[0];
}

export function nowTime() {
  return new Date().toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false });
}

export function roundTenth(minutes) {
  return Math.max(0.1, Math.round((minutes / 60) * 10) / 10);
}

export function parseTransformResponse(text) {
  const lines = String(text || "")
    .split("\n")
    .map(line => line.trim())
    .filter(Boolean);
  let code = null;
  let mins = null;
  const descLines = [];

  for (const line of lines) {
    if (line.startsWith("CODE:")) {
      code = line.replace("CODE:", "").trim() || null;
      continue;
    }
    if (line.startsWith("MINS:")) {
      const parsed = Number.parseInt(line.replace("MINS:", "").trim(), 10);
      mins = Number.isFinite(parsed) ? parsed : null;
      continue;
    }
    descLines.push(line);
  }

  return {
    desc: descLines.join(" ").trim() || null,
    code,
    mins,
  };
}

export function getAnthropicApiKey(source = globalThis) {
  return source?.ANTHROPIC_API_KEY || source?.anthropicApiKey || source?.__ANTHROPIC_API_KEY__ || null;
}

export function buildAnthropicHeaders(apiKey) {
  if (!apiKey) {
    throw new Error("Missing Anthropic API key. Set window.ANTHROPIC_API_KEY before using transform.");
  }

  return {
    "Content-Type": "application/json",
    "x-api-key": apiKey,
    "anthropic-version": ANTHROPIC_VERSION,
  };
}
