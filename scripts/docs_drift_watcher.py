#!/usr/bin/env python3
"""docs_drift_watcher.py — daily documentation drift surveillance.

Scans merged PRs since the last run, extracts the API symbols touched
in those PRs, flags docs pages that reference any of them, and writes
a drift report plus optional inline editor banners. The companion
workflow turns that working-tree state into a review PR.

Pure stdlib. No third-party packages. Safe to run anywhere Python 3.10+ runs.
The scheduled workflow uses Python 3.12 on ubuntu-latest.

Usage:
    python scripts/docs_drift_watcher.py \
        --repo <owner>/<repo> \
        --docs-root docs \
        --apply-banners

Environment:
    GITHUB_TOKEN — required for non-trivial API usage (rate-limited otherwise).
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from urllib.error import HTTPError
from urllib.request import Request, urlopen

GITHUB_API = "https://api.github.com"

DEFAULT_CONFIG: dict = {
    "docs_globs": ["**/*.md", "**/*.html", "**/*.mdx"],
    "code_extensions": [".py", ".mjs", ".js", ".ts", ".tsx", ".jsx"],
    "ignore_symbols": [
        "self", "cls", "main", "test", "setUp", "tearDown",
        "render", "create", "delete", "get", "set", "list",
        "post", "put", "update", "value", "items", "data",
    ],
    "min_symbol_length": 5,
    "ignore_doc_paths": ["docs/_drift/", "docs/portal/data/"],
    "max_prs_per_run": 50,
    "base_branch": "main",
}


# ---------- config & state ----------


def load_config(path: Path) -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if not path.exists():
        return _normalize(cfg)
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            items = [v.strip().strip("\"'") for v in value[1:-1].split(",")
                     if v.strip()]
            cfg[key] = items
        elif value.isdigit():
            cfg[key] = int(value)
        elif value:
            cfg[key] = value.strip("\"'")
    return _normalize(cfg)


def _normalize(cfg: dict) -> dict:
    if isinstance(cfg.get("ignore_symbols"), list):
        cfg["ignore_symbols"] = set(cfg["ignore_symbols"])
    return cfg


def load_state(path: Path) -> dict:
    if not path.exists():
        return {"last_run_utc": None, "last_pr_number": 0}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def parse_iso_timestamp(value: str | None) -> str | None:
    """Normalize ISO-8601 timestamps to UTC ``...Z`` for comparisons."""
    if not value:
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise SystemExit(f"Invalid ISO timestamp: {value!r}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def escape_markdown_inline(text: str) -> str:
    """Escape characters that break Markdown inline or link text."""
    return re.sub(r"([\\`*_{}\[\]()#+\-.!|])", r"\\\1", text)


# ---------- GitHub client ----------


class GitHub:
    def __init__(self, token: str | None) -> None:
        self.token = token

    def _request(self, url: str) -> list | dict:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "docs-drift-watcher",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = Request(url, headers=headers)
        try:
            with urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            if exc.code == 403 and "rate limit" in body.lower():
                raise SystemExit(
                    "GitHub rate limit hit — provide GITHUB_TOKEN."
                ) from exc
            raise

    def list_merged_prs(
        self,
        repo: str,
        base_branch: str,
        since_iso: str | None,
        max_prs: int,
    ) -> list[dict]:
        out: list[dict] = []
        page = 1
        while page <= 10 and len(out) < max_prs:
            url = (
                f"{GITHUB_API}/repos/{repo}/pulls"
                f"?state=closed&base={base_branch}"
                f"&sort=updated&direction=desc"
                f"&per_page=100&page={page}"
            )
            batch = self._request(url)
            if not isinstance(batch, list) or not batch:
                break
            for pr in batch:
                if not pr.get("merged_at"):
                    continue
                merged_at = parse_iso_timestamp(pr["merged_at"])
                if since_iso and merged_at and merged_at <= since_iso:
                    continue
                out.append(pr)
                if len(out) >= max_prs:
                    break
            if len(out) >= max_prs:
                break
            if len(batch) < 100:
                break
            if since_iso:
                oldest_updated = parse_iso_timestamp(
                    batch[-1].get("updated_at")
                )
                if oldest_updated and oldest_updated <= since_iso:
                    break
            page += 1
        out.sort(key=lambda p: p["merged_at"])
        return out

    def list_pr_files(self, repo: str, pr_number: int) -> list[dict]:
        out: list[dict] = []
        page = 1
        while page <= 10:
            url = (
                f"{GITHUB_API}/repos/{repo}/pulls/{pr_number}/files"
                f"?per_page=100&page={page}"
            )
            batch = self._request(url)
            if not isinstance(batch, list) or not batch:
                break
            out.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return out


# ---------- symbol extraction ----------


@dataclass
class Symbol:
    name: str
    kind: str
    source_file: str
    pr_number: int
    pr_title: str
    pr_url: str


_JS_EXPORT = re.compile(
    r"^\s*export\s+(?:async\s+)?(?:function|class|const|let)\s+([A-Za-z_][\w]*)",
    re.MULTILINE,
)
_JS_FN = re.compile(
    r"^\s*(?:async\s+)?function\s+([A-Za-z_][\w]*)", re.MULTILINE
)
_JS_CLASS = re.compile(r"^\s*class\s+([A-Z][\w]*)", re.MULTILINE)
_ROUTE = re.compile(
    r"""(?:@app\.route|app\.(?:get|post|put|patch|delete)|"""
    r"""router\.(?:get|post|put|patch|delete))\(\s*['\"]([^'\"]+)['\"]""",
    re.IGNORECASE,
)


def extract_python_symbols(code: str) -> list[tuple[str, str]]:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    out: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_"):
                out.append((node.name, "function"))
        elif isinstance(node, ast.ClassDef):
            out.append((node.name, "class"))
    return out


def extract_js_symbols(code: str) -> list[tuple[str, str]]:
    found: dict[str, str] = {}
    for name in _JS_EXPORT.findall(code):
        found[name] = "export"
    for name in _JS_FN.findall(code):
        found.setdefault(name, "function")
    for name in _JS_CLASS.findall(code):
        found.setdefault(name, "class")
    return list(found.items())


def extract_routes(code: str) -> list[tuple[str, str]]:
    return [(path, "route") for path in set(_ROUTE.findall(code))]


def extract_from_patch(filename: str, patch: str | None) -> list[tuple[str, str]]:
    if not patch:
        return []
    added_lines: list[str] = []
    removed_lines: list[str] = []
    for line in patch.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            added_lines.append(line[1:])
        elif line.startswith("-") and not line.startswith("---"):
            removed_lines.append(line[1:])
    body = "\n".join(added_lines + removed_lines)
    if filename.endswith(".py"):
        symbols = extract_python_symbols(body)
        if not symbols:
            symbols = _python_regex_fallback(body)
    elif filename.endswith((".mjs", ".js", ".ts", ".tsx", ".jsx")):
        symbols = extract_js_symbols(body)
    else:
        symbols = []
    symbols.extend(extract_routes(body))
    return symbols


_PY_DEF = re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_][\w]*)", re.MULTILINE)
_PY_CLASS = re.compile(r"^\s*class\s+([A-Z][\w]*)", re.MULTILINE)


def _python_regex_fallback(code: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for name in _PY_DEF.findall(code):
        if not name.startswith("_"):
            out.append((name, "function"))
    for name in _PY_CLASS.findall(code):
        out.append((name, "class"))
    return out


# ---------- doc scanning ----------


@dataclass
class DocHit:
    doc_path: str
    symbol: Symbol
    line_number: int
    excerpt: str


def iter_docs(
    root: Path, globs: list[str], ignore_prefixes: list[str]
) -> Iterator[Path]:
    seen: set[Path] = set()
    for pat in globs:
        for p in root.glob(pat):
            if not p.is_file() or p in seen:
                continue
            seen.add(p)
            rel = str(p).replace("\\", "/")
            if any(rel.startswith(prefix) for prefix in ignore_prefixes):
                continue
            yield p


def _line_contains_symbol(line: str, name: str, kind: str) -> bool:
    if kind == "route":
        return name in line
    return re.search(rf"\b{re.escape(name)}\b", line) is not None


def _build_word_symbol_pattern(
    symbols_by_name: dict[str, Symbol],
) -> re.Pattern[str] | None:
    names = [n for n, s in symbols_by_name.items() if s.kind != "route"]
    if not names:
        return None
    names.sort(key=len, reverse=True)
    return re.compile(
        rf"\b({'|'.join(re.escape(name) for name in names)})\b"
    )


def scan_doc(
    doc_path: Path, symbols_by_name: dict[str, Symbol]
) -> list[DocHit]:
    try:
        text = doc_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return []
    hits: list[DocHit] = []
    word_pattern = _build_word_symbol_pattern(symbols_by_name)
    route_syms = {
        name: sym for name, sym in symbols_by_name.items() if sym.kind == "route"
    }
    for i, line in enumerate(text.splitlines(), start=1):
        if word_pattern:
            match = word_pattern.search(line)
            if match:
                name = match.group(1)
                hits.append(DocHit(
                    str(doc_path), symbols_by_name[name], i, line.strip()[:240]
                ))
                continue
        for name, sym in route_syms.items():
            if _line_contains_symbol(line, name, sym.kind):
                hits.append(DocHit(
                    str(doc_path), sym, i, line.strip()[:240]
                ))
                break
    return hits


# ---------- banners & report ----------

BANNER_BEGIN = "<!-- DOCS-DRIFT:BEGIN -->"
BANNER_END = "<!-- DOCS-DRIFT:END -->"
_BANNER_RE = re.compile(
    re.escape(BANNER_BEGIN) + r".*?" + re.escape(BANNER_END) + r"\n*",
    re.DOTALL,
)


def render_banner(hits: list[DocHit], run_iso: str) -> str:
    by_pr: dict[int, list[DocHit]] = {}
    for h in hits:
        by_pr.setdefault(h.symbol.pr_number, []).append(h)
    rows: list[str] = []
    for pr_number in sorted(by_pr):
        sample = by_pr[pr_number][0]
        symbols = ", ".join(sorted({
            f"`{h.symbol.name}`" for h in by_pr[pr_number]
        }))
        title = escape_markdown_inline(sample.symbol.pr_title)
        rows.append(f"- **#{pr_number}** — {title}")
        rows.append(f"  symbols: {symbols}")
    return (
        f"{BANNER_BEGIN}\n"
        f"> **Documentation drift detected** _(scanned {run_iso})_\n"
        f">\n"
        f"> The watcher matched API symbols that changed in recently merged "
        f"PRs against this page. Confirm the page is still accurate, edit "
        f"if needed, then remove this banner.\n"
        f">\n"
        + "\n".join(f"> {line}" for line in rows)
        + f"\n{BANNER_END}\n\n"
    )


def _insert_after_frontmatter(text: str, block: str) -> str:
    stripped = text.lstrip("\ufeff")
    if stripped.startswith("---"):
        parts = stripped.split("---", 2)
        if len(parts) >= 3:
            return f"---{parts[1]}---\n\n{block}{parts[2].lstrip()}"
    return block + stripped


def apply_banner(doc_path: Path, banner: str) -> bool:
    try:
        text = doc_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return False
    stripped = _BANNER_RE.sub("", text)
    new_text = _insert_after_frontmatter(stripped, banner)
    if new_text == text:
        return False
    doc_path.write_text(new_text, encoding="utf-8")
    return True


def render_report(
    hits: list[DocHit], run_iso: str, prs: list[dict], since_iso: str | None
) -> str:
    by_doc: dict[str, list[DocHit]] = {}
    for h in hits:
        by_doc.setdefault(h.doc_path, []).append(h)
    lines: list[str] = [
        f"# Docs Drift Report — {run_iso[:10]}",
        "",
        "_Auto-generated by `scripts/docs_drift_watcher.py`._",
        "",
        f"- Scan window start: `{since_iso or 'beginning of time'}`",
        f"- Scan run: `{run_iso}`",
        f"- Merged PRs reviewed: **{len(prs)}**",
        f"- Doc pages flagged: **{len(by_doc)}**",
        f"- Symbol mentions: **{len(hits)}**",
        "",
        "## Flagged pages",
        "",
    ]
    if not by_doc:
        lines += [
            "_No drift detected. Documentation is clean for this window._",
            "",
        ]
    for doc, ds in sorted(by_doc.items()):
        lines += [f"### `{doc}`", ""]
        for h in ds:
            lines.append(
                f"- line {h.line_number} — `{h.symbol.name}` "
                f"(PR #{h.symbol.pr_number} · {h.symbol.kind} in "
                f"`{h.symbol.source_file}`): {h.excerpt}"
            )
        lines.append("")
    lines += ["## Merged PRs scanned", ""]
    for pr in prs:
        title = escape_markdown_inline(pr["title"])
        login = escape_markdown_inline(
            (pr.get("user") or {}).get("login") or "unknown"
        )
        lines.append(
            f"- #{pr['number']} — [{title}]({pr['html_url']}) "
            f"by @{login}, merged {pr['merged_at']}"
        )
    lines.append("")
    return "\n".join(lines)


# ---------- orchestration ----------


def collect_symbols(
    gh: GitHub,
    repo: str,
    prs: list[dict],
    config: dict,
) -> dict[str, Symbol]:
    symbols_by_name: dict[str, Symbol] = {}
    ignore: set[str] = set(config.get("ignore_symbols") or [])
    min_len = int(config.get("min_symbol_length") or 4)
    code_exts = tuple(config.get("code_extensions") or [".py"])
    for pr in prs:
        try:
            files = gh.list_pr_files(repo, pr["number"])
        except Exception as exc:  # noqa: BLE001
            print(
                f"[drift] skipping PR #{pr['number']}: {exc}",
                file=sys.stderr,
            )
            continue
        for f in files:
            name = f.get("filename") or ""
            if not name.endswith(code_exts):
                continue
            for sym_name, kind in extract_from_patch(name, f.get("patch")):
                if kind != "route" and len(sym_name) < min_len:
                    continue
                if sym_name in ignore:
                    continue
                symbols_by_name.setdefault(
                    sym_name,
                    Symbol(
                        name=sym_name,
                        kind=kind,
                        source_file=name,
                        pr_number=pr["number"],
                        pr_title=pr["title"],
                        pr_url=pr["html_url"],
                    ),
                )
    return symbols_by_name


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", required=True, help="owner/name of source repo")
    ap.add_argument("--docs-repo", default=None,
                    help="owner/name of docs repo (recorded in summary JSON; "
                         "same-repo checkout is assumed today)")
    ap.add_argument("--docs-root", default="docs")
    ap.add_argument("--state", default=".docs-drift/state.json")
    ap.add_argument("--config", default=".docs-drift/config.yml")
    ap.add_argument("--report-dir", default="docs/_drift")
    ap.add_argument("--output", default=".docs-drift/last-run.json")
    ap.add_argument("--apply-banners", action="store_true")
    ap.add_argument("--since", default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    docs_root = Path(args.docs_root)
    state_path = Path(args.state)
    config_path = Path(args.config)
    report_dir = Path(args.report_dir)

    config = load_config(config_path)
    state = load_state(state_path)
    since_raw = args.since or state.get("last_run_utc")
    since_iso = parse_iso_timestamp(since_raw) if since_raw else None
    since_pr = int(state.get("last_pr_number") or 0)

    token = os.environ.get("GITHUB_TOKEN")
    gh = GitHub(token)

    run_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(
        f"[drift] run={run_iso} repo={args.repo} "
        f"since={since_iso} since_pr={since_pr}",
        file=sys.stderr,
    )

    prs = gh.list_merged_prs(
        args.repo,
        base_branch=str(config.get("base_branch") or "main"),
        since_iso=since_iso,
        max_prs=int(config.get("max_prs_per_run") or 50),
    )
    print(f"[drift] merged PRs in window: {len(prs)}", file=sys.stderr)

    symbols_by_name = collect_symbols(gh, args.repo, prs, config)
    print(
        f"[drift] candidate symbols: {len(symbols_by_name)}",
        file=sys.stderr,
    )

    all_hits: list[DocHit] = []
    ignore_doc_prefixes = list(config.get("ignore_doc_paths") or [])
    doc_globs = list(config.get("docs_globs") or ["**/*.md", "**/*.html"])
    if symbols_by_name and docs_root.exists():
        for doc in iter_docs(docs_root, doc_globs, ignore_doc_prefixes):
            all_hits.extend(scan_doc(doc, symbols_by_name))

    flagged_docs = sorted({h.doc_path for h in all_hits})
    print(
        f"[drift] doc hits: {len(all_hits)} across "
        f"{len(flagged_docs)} pages",
        file=sys.stderr,
    )

    if not args.dry_run:
        report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"REPORT-{run_iso[:10]}.md"
    if not args.dry_run:
        report_path.write_text(
            render_report(all_hits, run_iso, prs, since_iso),
            encoding="utf-8",
        )

    touched_docs: list[str] = []
    if args.apply_banners and all_hits and not args.dry_run:
        by_doc: dict[str, list[DocHit]] = {}
        for h in all_hits:
            by_doc.setdefault(h.doc_path, []).append(h)
        for doc_path, doc_hits in by_doc.items():
            banner = render_banner(doc_hits, run_iso)
            if apply_banner(Path(doc_path), banner):
                touched_docs.append(doc_path)

    new_state = {
        "last_run_utc": run_iso,
        "last_pr_number": max(
            [pr["number"] for pr in prs] + [since_pr], default=since_pr
        ),
        "last_window_pr_count": len(prs),
        "last_window_hits": len(all_hits),
    }
    if not args.dry_run:
        save_state(state_path, new_state)

    summary = {
        "run_utc": run_iso,
        "repo": args.repo,
        "docs_repo": args.docs_repo or args.repo,
        "since_utc": since_iso,
        "since_pr": since_pr,
        "merged_prs": [
            {
                "number": pr["number"],
                "title": pr["title"],
                "merged_at": pr["merged_at"],
                "html_url": pr["html_url"],
                "author": pr.get("user", {}).get("login"),
            }
            for pr in prs
        ],
        "symbols": [
            {
                "name": s.name,
                "kind": s.kind,
                "pr_number": s.pr_number,
                "source_file": s.source_file,
            }
            for s in symbols_by_name.values()
        ],
        "hits": [
            {
                "doc": h.doc_path,
                "line": h.line_number,
                "symbol": h.symbol.name,
                "pr": h.symbol.pr_number,
                "excerpt": h.excerpt,
            }
            for h in all_hits
        ],
        "flagged_docs": flagged_docs,
        "touched_docs": touched_docs,
        "report_path": str(report_path),
        "drift_detected": bool(all_hits),
    }
    if not args.dry_run:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(
            json.dumps(summary, indent=2) + "\n", encoding="utf-8"
        )

    if all_hits:
        print(
            f"[drift] DRIFT DETECTED — {len(all_hits)} hits, "
            f"{len(touched_docs)} pages updated.",
            file=sys.stderr,
        )
    else:
        print("[drift] no drift detected.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
