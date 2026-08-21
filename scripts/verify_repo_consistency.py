#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = REPO_ROOT / "catalog" / "manifest.md"
DEFAULT_OUTPUT = REPO_ROOT / "catalog" / "intake" / "repo_consistency_report.json"
IGNORE_SOURCE_PARTS = {"onedrive_ingest", "__pycache__"}
IGNORE_SOURCE_NAMES = {".gitkeep", "README.md"}
IGNORE_EXACT_SOURCE_PATHS = {
    "sources/emails/consolidated_emails.json",
    "sources/skills/tracker_helpers.mjs",
}
IGNORE_SOURCE_PATH_PREFIXES = {
    "sources/depositions/",
    "sources/emails/md/",
}
IGNORE_SKILL_CODE_SUFFIXES = {".js", ".jsx", ".mjs", ".ts", ".tsx"}
TEXTUAL_COMPANION_SUFFIXES = {".md", ".txt"}
REPO_PATH_PATTERN = re.compile(
    r"(?P<path>(?:sources|references)/.+|(?:README|CLAUDE|SKILL|stonewall_synergy_v13)\.md)"
)


@dataclass(frozen=True)
class ManifestRow:
    artifact_id: str
    file_field: str
    repo_path: str | None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_stem(path: Path) -> str:
    stem = path.stem.lower()
    stem = stem.replace(".pdf", "")
    stem = re.sub(r"\s+\((?:copy|\d+)\)$", "", stem)
    stem = re.sub(r"\s+copy$", "", stem)
    stem = re.sub(r"\s+v\d+$", "", stem)
    stem = re.sub(r"[.\s_-]+", " ", stem)
    return stem.strip()


def extract_repo_path(file_field: str) -> str | None:
    match = REPO_PATH_PATTERN.search(file_field.strip())
    return match.group("path") if match else None


def parse_manifest_rows(manifest_path: Path) -> list[ManifestRow]:
    rows: list[ManifestRow] = []
    if not manifest_path.exists():
        return rows
    for line in manifest_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.startswith("| A"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 9:
            continue
        artifact_id, file_field = cells[0], cells[1]
        rows.append(
            ManifestRow(
                artifact_id=artifact_id,
                file_field=file_field,
                repo_path=extract_repo_path(file_field),
            )
        )
    return rows


def is_generated_sidecar(path: Path) -> bool:
    name = path.name.lower()
    if name.endswith(".pdf.md"):
        return True
    return bool(re.search(r"(?:[._-](?:pdf|docx|xlsx|csv|txt))\.md$", name))


def should_track_source(path: Path, repo_root: Path) -> bool:
    rel_path = path.relative_to(repo_root).as_posix()
    if any(part in IGNORE_SOURCE_PARTS for part in path.parts):
        return False
    if path.name in IGNORE_SOURCE_NAMES:
        return False
    if rel_path in IGNORE_EXACT_SOURCE_PATHS:
        return False
    if any(rel_path.startswith(prefix) for prefix in IGNORE_SOURCE_PATH_PREFIXES):
        return False
    if is_generated_sidecar(path):
        return False
    if path.parent.name == "skills" and path.suffix.lower() in IGNORE_SKILL_CODE_SUFFIXES:
        return False
    if path.name.endswith("_INDEX.md"):
        return False
    return True


def has_pdf_sidecar(pdf_path: Path) -> bool:
    return (
        pdf_path.with_name(f"{pdf_path.name}.md").exists()
        or pdf_path.with_suffix(".md").exists()
    )


def sort_family_paths(paths: list[str]) -> list[str]:
    def sort_key(rel_path: str) -> tuple[int, int, str]:
        suffix = Path(rel_path).suffix.lower()
        textual_rank = 0 if suffix in TEXTUAL_COMPANION_SUFFIXES else 1
        suffix_rank = {
            ".md": 0,
            ".txt": 1,
            ".csv": 2,
            ".xlsx": 3,
            ".docx": 4,
            ".pdf": 5,
        }.get(suffix, 9)
        return (textual_rank, suffix_rank, rel_path.lower())

    return sorted(paths, key=sort_key)


def choose_family_representative(paths: list[str]) -> str:
    return sort_family_paths(paths)[0]


def split_duplicate_groups(paths: list[str]) -> tuple[list[str], list[str]]:
    canonical_paths = sorted(path for path in paths if "/variants/" not in path)
    variant_paths = sorted(path for path in paths if "/variants/" in path)
    return canonical_paths, variant_paths


def build_report(repo_root: Path = REPO_ROOT, manifest_path: Path = DEFAULT_MANIFEST) -> dict:
    source_root = repo_root / "sources"
    manifest_rows = parse_manifest_rows(manifest_path)
    manifest_repo_paths = {
        row.repo_path for row in manifest_rows if row.repo_path
    }

    manifest_missing_paths = []
    for row in manifest_rows:
        if not row.repo_path:
            continue
        if not (repo_root / row.repo_path).exists():
            manifest_missing_paths.append(
                {
                    "id": row.artifact_id,
                    "file_field": row.file_field,
                    "repo_path": row.repo_path,
                }
            )

    tracked_source_files: list[Path] = []
    uncataloged_canonical_sources: list[str] = []
    uncataloged_variant_sources: list[str] = []
    pdf_missing_markdown: list[str] = []
    exact_duplicate_hashes: dict[str, list[str]] = defaultdict(list)
    stem_clusters: dict[str, list[str]] = defaultdict(list)

    for path in sorted(source_root.rglob("*")):
        if not path.is_file():
            continue
        if not should_track_source(path, repo_root):
            continue

        rel_path = path.relative_to(repo_root).as_posix()
        tracked_source_files.append(path)
        exact_duplicate_hashes[sha256_file(path)].append(rel_path)
        stem_clusters[normalize_stem(path)].append(rel_path)

        if path.suffix.lower() == ".pdf" and not has_pdf_sidecar(path):
            pdf_missing_markdown.append(rel_path)

    variant_clusters = []
    unresolved_duplicate_name_clusters = []
    for normalized_stem, paths in sorted(stem_clusters.items()):
        if len(paths) < 2:
            continue
        canonical_paths, variant_paths = split_duplicate_groups(paths)
        if canonical_paths and variant_paths:
            variant_clusters.append(
                {
                    "normalized_stem": normalized_stem,
                    "canonical_paths": sort_family_paths(canonical_paths),
                    "variant_paths": sort_family_paths(variant_paths),
                }
            )
        suffix_counts: dict[str, int] = defaultdict(int)
        for rel_path in canonical_paths:
            suffix_counts[Path(rel_path).suffix.lower()] += 1
        if any(count > 1 for count in suffix_counts.values()):
            unresolved_duplicate_name_clusters.append(
                {
                    "normalized_stem": normalized_stem,
                    "paths": sort_family_paths(canonical_paths),
                }
            )

    cataloged_family_representatives: set[str] = set()
    for normalized_stem, paths in stem_clusters.items():
        canonical_paths, variant_paths = split_duplicate_groups(paths)
        if canonical_paths:
            if any(path in manifest_repo_paths for path in canonical_paths):
                cataloged_family_representatives.add(choose_family_representative(canonical_paths))
            else:
                uncataloged_canonical_sources.append(choose_family_representative(canonical_paths))
        if variant_paths and not any(path in manifest_repo_paths for path in variant_paths):
            uncataloged_variant_sources.extend(sort_family_paths(variant_paths))

    exact_duplicate_canonical_conflicts = []
    exact_duplicate_variant_groups = []
    for digest, paths in sorted(exact_duplicate_hashes.items()):
        if len(paths) < 2:
            continue
        canonical_paths, variant_paths = split_duplicate_groups(paths)
        row = {"sha256": digest, "paths": sorted(paths)}
        if len(canonical_paths) > 1:
            exact_duplicate_canonical_conflicts.append(row)
        elif canonical_paths and variant_paths:
            exact_duplicate_variant_groups.append(row)
        elif len(variant_paths) > 1:
            exact_duplicate_variant_groups.append(row)

    return {
        "repo_root": str(repo_root),
        "manifest_path": str(manifest_path),
        "manifest_row_count": len(manifest_rows),
        "manifest_repo_path_count": len(manifest_repo_paths),
        "tracked_source_file_count": len(tracked_source_files),
        "manifest_missing_paths": manifest_missing_paths,
        "uncataloged_canonical_sources": sorted(uncataloged_canonical_sources),
        "uncataloged_variant_sources": sorted(uncataloged_variant_sources),
        "pdf_missing_markdown": sorted(pdf_missing_markdown),
        "variant_clusters": variant_clusters,
        "unresolved_duplicate_name_clusters": unresolved_duplicate_name_clusters,
        "exact_duplicate_canonical_conflicts": exact_duplicate_canonical_conflicts,
        "exact_duplicate_variant_groups": exact_duplicate_variant_groups,
    }


def has_blocking_issues(report: dict) -> bool:
    blocking_keys = (
        "manifest_missing_paths",
        "uncataloged_canonical_sources",
        "pdf_missing_markdown",
        "unresolved_duplicate_name_clusters",
        "exact_duplicate_canonical_conflicts",
    )
    return any(report.get(key) for key in blocking_keys)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Stonewall repo consistency.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument(
        "--fail-on-issues",
        action="store_true",
        help="Exit 1 when blocking consistency issues are detected.",
    )
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    report = build_report(REPO_ROOT, manifest_path)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"Manifest rows: {report['manifest_row_count']}")
    print(f"Manifest repo paths: {report['manifest_repo_path_count']}")
    print(f"Tracked source files: {report['tracked_source_file_count']}")
    print(f"Missing manifest paths: {len(report['manifest_missing_paths'])}")
    print(f"Uncataloged canonical sources: {len(report['uncataloged_canonical_sources'])}")
    print(f"Uncataloged variant sources: {len(report['uncataloged_variant_sources'])}")
    print(f"PDFs missing markdown: {len(report['pdf_missing_markdown'])}")
    print(f"Variant clusters: {len(report['variant_clusters'])}")
    print(f"Unresolved duplicate-name clusters: {len(report['unresolved_duplicate_name_clusters'])}")
    print(f"Exact duplicate canonical conflicts: {len(report['exact_duplicate_canonical_conflicts'])}")
    print(f"Exact duplicate variant groups: {len(report['exact_duplicate_variant_groups'])}")
    print(f"Report written to {output_path}")
    if args.fail_on_issues and has_blocking_issues(report):
        print("Blocking consistency issues detected.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
