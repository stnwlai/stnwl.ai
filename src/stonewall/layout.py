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
