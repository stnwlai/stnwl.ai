#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "catalog" / "intake" / "repo_sweep_report.json"
IGNORE_DIRS = {
    ".git",
    ".next",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "venv",
}
IGNORE_SWEEP_PARTS = {"onedrive_ingest"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_repo_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in IGNORE_DIRS for part in path.parts):
            continue
        files.append(path)
    return files


def normalize_stem(path: Path) -> str:
    stem = path.stem.lower()
    stem = stem.replace(".pdf", "")
    stem = re.sub(r"\s+\((?:copy|\d+)\)$", "", stem)
    stem = re.sub(r"\s+copy$", "", stem)
    stem = re.sub(r"\s+v\d+$", "", stem)
    stem = re.sub(r"[.\s_-]+", " ", stem)
    return stem.strip()


def has_pdf_sidecar(pdf_path: Path) -> bool:
    sidecar = pdf_path.with_name(f"{pdf_path.name}.md")
    sibling = pdf_path.with_suffix(".md")
    return sidecar.exists() or sibling.exists()


def build_report() -> dict:
    repo_files = iter_repo_files(REPO_ROOT)
    sources_files = [
        path for path in repo_files
        if path.is_relative_to(REPO_ROOT / "sources") and not any(part in IGNORE_SWEEP_PARTS for part in path.parts)
    ]

    hashes: dict[str, list[str]] = defaultdict(list)
    for path in sources_files:
        hashes[sha256_file(path)].append(path.relative_to(REPO_ROOT).as_posix())
    exact_duplicates = [
        {"sha256": digest, "paths": sorted(paths)}
        for digest, paths in hashes.items()
        if len(paths) > 1
    ]

    stem_clusters: dict[str, list[str]] = defaultdict(list)
    for path in sources_files:
        if path.suffix.lower() == ".md" and path.name.lower().endswith(".pdf.md"):
            continue
        key = normalize_stem(path)
        if key in {"readme", ".gitkeep"}:
            continue
        stem_clusters[key].append(path.relative_to(REPO_ROOT).as_posix())
    related_name_clusters = [
        {"normalized_stem": stem, "paths": sorted(paths)}
        for stem, paths in stem_clusters.items()
        if len(paths) > 1
    ]

    pdf_rows = []
    for pdf_path in sorted([path for path in sources_files if path.suffix.lower() == ".pdf"]):
        pdf_rows.append(
            {
                "pdf_path": pdf_path.relative_to(REPO_ROOT).as_posix(),
                "has_markdown_derivative": has_pdf_sidecar(pdf_path),
                "size_bytes": pdf_path.stat().st_size,
            }
        )

    return {
        "repo_root": str(REPO_ROOT),
        "file_count": len(repo_files),
        "sources_file_count": len(sources_files),
        "exact_duplicates": exact_duplicates,
        "related_name_clusters": related_name_clusters,
        "pdfs": pdf_rows,
        "pdf_missing_markdown": [row["pdf_path"] for row in pdf_rows if not row["has_markdown_derivative"]],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a repo-wide sweep report for Stonewall.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()

    report = build_report()
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"Repo files: {report['file_count']}")
    print(f"Sources files: {report['sources_file_count']}")
    print(f"Exact duplicate groups: {len(report['exact_duplicates'])}")
    print(f"Related-name clusters: {len(report['related_name_clusters'])}")
    print(f"PDFs missing markdown: {len(report['pdf_missing_markdown'])}")
    print(f"Report written to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
