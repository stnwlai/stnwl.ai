#!/usr/bin/env python3
"""Check or refresh the exact public-tree publication manifest."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from stonewall.errors import PublicationBoundaryError
from stonewall.publication import check_boundary, load_config, write_manifest

EXIT_CLEAN = 0
EXIT_GUARD_FAILURE = 3
EXIT_BOUNDARY_FINDING = 10


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-manifest", action="store_true")
    args = parser.parse_args(argv)
    try:
        config = load_config(REPO_ROOT / "public-boundary.toml")
        if args.write_manifest:
            findings = check_boundary(REPO_ROOT, config)
            blockers = [
                finding
                for finding in findings
                if finding.rule not in {"manifest_missing", "manifest_drift"}
            ]
            if blockers:
                for finding in blockers:
                    print(finding.render())
                print(f"Public boundary blocked: {len(blockers)} finding(s)")
                return EXIT_BOUNDARY_FINDING
            payload = write_manifest(REPO_ROOT, config)
            print(f"Public tree manifest written: {payload['path_count']} paths")
            return EXIT_CLEAN
        findings = check_boundary(REPO_ROOT, config)
    except PublicationBoundaryError as exc:
        print(f"Public boundary guard failed: {exc}", file=sys.stderr)
        return EXIT_GUARD_FAILURE
    if findings:
        for finding in findings:
            print(finding.render())
        print(f"Public boundary blocked: {len(findings)} finding(s)")
        return EXIT_BOUNDARY_FINDING
    print("Public boundary check passed.")
    return EXIT_CLEAN


if __name__ == "__main__":
    raise SystemExit(main())
