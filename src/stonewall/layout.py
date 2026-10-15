"""Repository-relative locations shared by the command surface and checks."""

from __future__ import annotations

from pathlib import PurePosixPath

CORPUS_DIR = PurePosixPath("examples/corpus")
POLICY_FILE = PurePosixPath("examples/disclosure-policy.toml")
SPEAKERS_FILE = PurePosixPath("examples/speakers.toml")
ANSWERS_DIR = PurePosixPath("examples/answers")
DEFECTS_FILE = PurePosixPath("examples/seeded-defects.toml")
README_FILE = PurePosixPath("README.md")
BOUNDARY_FILE = PurePosixPath("public-boundary.toml")


def canonical_relative_path(value: object) -> PurePosixPath | None:
    """*value* as a canonical relative POSIX path, or None when it is not one."""
    if not isinstance(value, str) or not value or "\\" in value:
        return None
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        return None
    return path
