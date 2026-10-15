"""Checks that can fail: every check is run against seeded defects it must reject.

Each check runs on a staged copy of exactly the publishable tree. On the
unmodified copy it must report nothing and write nothing. Each seeded defect is
applied to a fresh copy, and its check must reject it for the named rule.
Checks read; they never write. Reports carry check names, defect names, rule ids
and paths, never the content of a defect or of the tree.

Only the bundle and unit checks start subprocesses, and they run the staged
tree's own src, so they are the only checks a defect in src/ may target.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from . import transcripts
from .attribution import load_speakers, unregistered_labels
from .compiler import CompiledCorpus, compile_corpus
from .disclosure import load_policy, unknown_designations
from .errors import (
    CheckHarnessError,
    CorpusValidationError,
    DisclosureError,
    PublicationBoundaryError,
    SpeakerRegistryError,
    StonewallError,
)
from .grounding import audit_answer, load_answer
from .hashing import merkle_root, sha256_file
from .layout import (
    ANSWERS_DIR,
    BOUNDARY_FILE,
    CORPUS_DIR,
    DEFECTS_FILE,
    POLICY_FILE,
    README_FILE,
    SPEAKERS_FILE,
    canonical_relative_path,
)
from .models import Finding
from .publication import candidate_paths, check_boundary, load_config

SUBPROCESS_CHECKS = frozenset({"bundle", "unit"})
UNIT_TESTS: tuple[str, ...] = (
    "tests.test_grounding.NonInterferenceTests.test_privileged_record_cannot_reorder_model_packet",
    "tests.test_evidence_fabric.RetrievalTests.test_citation_rejects_tampered_span_digest",
    "tests.test_grounding.AuditTests.test_fabricated_fixture_findings_are_pinned",
    "tests.test_disclosure.PolicyTests.test_loosened_policy_is_refused",
)
OPS = frozenset({"append", "replace", "write"})
SUBPROCESS_TIMEOUT = 60
_DEFECT_KEYS = frozenset({"check", "expect", "name", "new", "old", "op", "parts", "path"})
_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_RULE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_UNIT_FAILURE_RE = re.compile(r"^FAIL: (test_\w+) ", re.MULTILINE)
_UNIT_ERROR_RE = re.compile(r"^ERROR: test_\w+ ", re.MULTILINE)


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    run: Callable[[Path, Path], list[Finding]]  # (tree root, scratch dir outside it)


@dataclass(frozen=True, slots=True)
class SeededDefect:
    name: str
    check: str
    expect: str
    op: str
    path: PurePosixPath
    old: str = ""
    new: str = ""
    parts: tuple[str, ...] = ()


def _saw(findings: tuple[Finding, ...]) -> str:
    """Rule ids and locations only, never content."""
    return ", ".join(f"{f.rule} {f.path}:{f.line}" for f in findings) or "none"


@dataclass(frozen=True, slots=True)
class CheckOutcome:
    name: str
    rules: tuple[str, ...]
    wrote: tuple[str, ...]
    findings: tuple[Finding, ...] = ()

    @property
    def passed(self) -> bool:
        return not self.rules and not self.wrote


@dataclass(frozen=True, slots=True)
class DefectOutcome:
    name: str
    check: str
    expect: str
    status: str  # rejected | survived | wrong_reason | wrote_tree | check_crashed
    rules: tuple[str, ...]
    wrote: tuple[str, ...]
    findings: tuple[Finding, ...] = ()


@dataclass(frozen=True, slots=True)
class CheckReport:
    tree_sha256: str
    clean: tuple[CheckOutcome, ...]
    defects: tuple[DefectOutcome, ...]
    unchallenged: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return (
            all(outcome.passed for outcome in self.clean)
            and all(defect.status == "rejected" for defect in self.defects)
            and not self.unchallenged
        )

    def _counts(self, name: str) -> tuple[int, int]:
        mine = [defect for defect in self.defects if defect.check == name]
        return sum(defect.status == "rejected" for defect in mine), len(mine)

    def to_dict(self) -> dict[str, Any]:
        checks = [
            {"defects": self._counts(o.name)[1],
             "findings": [finding.to_dict() for finding in o.findings], "name": o.name,
             "rejected": self._counts(o.name)[0], "unmodified_rules": list(o.rules),
             "wrote": list(o.wrote)}
            for o in self.clean
        ]
        defects = [
            {"check": d.check, "expect": d.expect,
             "findings": [finding.to_dict() for finding in d.findings], "name": d.name,
             "rules": list(d.rules), "status": d.status, "wrote": list(d.wrote)}
            for d in self.defects
        ]
        return {"checks": checks, "defects": defects, "passed": self.passed,
                "schema_version": 1, "tree_sha256": self.tree_sha256,
                "unchallenged": list(self.unchallenged)}

    def render_text(self) -> str:
        header = f"{len(self.clean)} checks  {len(self.defects)} seeded defects"
        lines = [f"tree {self.tree_sha256[:12]}  {header}"]
        for outcome in self.clean:
            rejected, total = self._counts(outcome.name)
            fields = [
                f"{outcome.name:<12} unmodified {'pass' if outcome.passed else 'FAIL'}",
                "WROTE" if outcome.wrote else "wrote nothing",
                f"{rejected}/{total} defects rejected",
            ]
            if outcome.rules:
                fields.append(f"saw: {_saw(outcome.findings)}")
            lines.append("  ".join(fields))
        for defect in self.defects:
            if defect.status != "rejected":
                lines.append(
                    f"{defect.status.upper()} {defect.name}"
                    f" ({defect.check} expected {defect.expect}, saw: {_saw(defect.findings)})"
                )
        lines.extend(f"UNCHALLENGED {name}" for name in self.unchallenged)
        lines.append("PASS" if self.passed else "FAIL")
        return "\n".join(lines)


def _subprocess_env(root: Path, **extra: str) -> dict[str, str]:
    env = dict(os.environ)
    env.update(PYTHONPATH=str(root / "src"), PYTHONDONTWRITEBYTECODE="1", **extra)
    return env


def check_answers(root: Path, scratch: Path) -> list[Finding]:
    try:
        corpus = compile_corpus(root / CORPUS_DIR)
        policy = load_policy(root / POLICY_FILE)
        speakers = load_speakers(root / SPEAKERS_FILE)
        answers = sorted((root / ANSWERS_DIR).rglob("*.md"))
    except (OSError, StonewallError):
        answers = []
    if not answers:
        return [Finding(ANSWERS_DIR.as_posix(), 0, "answers_unavailable")]
    findings: list[Finding] = []
    for path in answers:
        source = (ANSWERS_DIR / path.relative_to(root / ANSWERS_DIR).as_posix()).as_posix()
        try:
            document = load_answer(path, source=source)
            audit = audit_answer(document, corpus, policy, speakers)
        except StonewallError:
            findings.append(Finding(source, 0, "answer_invalid"))
            continue
        if document.expect is None:
            findings.extend(Finding(source, item.line, item.rule) for item in audit.findings)
        elif audit.rules() != document.expect:
            findings.append(Finding(source, 0, "expectation_unmet"))
    return findings


def check_boundary_files(root: Path, scratch: Path) -> list[Finding]:
    try:
        return check_boundary(root, load_config(root / BOUNDARY_FILE))
    except PublicationBoundaryError:
        return [Finding(BOUNDARY_FILE.as_posix(), 0, "boundary_unavailable")]


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def check_bundle(root: Path, scratch: Path) -> list[Finding]:
    location = CORPUS_DIR.as_posix()
    outputs = []
    for seed in ("1", "2"):
        output = scratch / f"seed{seed}"
        command = [
            sys.executable, "-B", "-m", "stonewall", "--corpus", location,
            "build", "--output", str(output),
        ]
        try:
            completed = subprocess.run(
                command, cwd=root, env=_subprocess_env(root, PYTHONHASHSEED=seed),
                capture_output=True, timeout=SUBPROCESS_TIMEOUT, check=False,
            )
        except subprocess.TimeoutExpired:
            return [Finding(location, 0, "bundle_timeout")]
        if completed.returncode != 0:
            return [Finding(location, 0, "bundle_invalid")]
        outputs.append(_tree_bytes(output))
    if outputs[0] != outputs[1]:
        return [Finding(location, 0, "bundle_not_reproducible")]
    return []


def check_corpus(root: Path, scratch: Path) -> list[Finding]:
    try:
        compile_corpus(root / CORPUS_DIR)
    except StonewallError as exc:
        rule = exc.rule if isinstance(exc, CorpusValidationError) else "corpus_invalid"
        return [Finding(CORPUS_DIR.as_posix(), 0, rule)]
    return []


def _located(
    root: Path, pairs: Callable[[CompiledCorpus], Iterable[tuple[str, int]]], rule: str
) -> list[Finding]:
    """Findings for ``(artifact_id, line)`` pairs, at the record's repository path."""
    try:
        corpus = compile_corpus(root / CORPUS_DIR)
    except StonewallError:
        return [Finding(CORPUS_DIR.as_posix(), 0, "corpus_unavailable")]
    findings = []
    for artifact_id, line in pairs(corpus):
        artifact = corpus.artifact(artifact_id)
        path = CORPUS_DIR / artifact.path if artifact else CORPUS_DIR
        findings.append(Finding(path.as_posix(), line, rule))
    return findings


def check_disclosure(root: Path, scratch: Path) -> list[Finding]:
    try:
        policy = load_policy(root / POLICY_FILE)
    except DisclosureError as exc:
        return [Finding(POLICY_FILE.as_posix(), 0, exc.rule)]
    return _located(
        root,
        lambda corpus: ((i, 0) for i in unknown_designations(corpus, policy)),
        "unknown_designation",
    )


def check_speakers(root: Path, scratch: Path) -> list[Finding]:
    try:
        registry = load_speakers(root / SPEAKERS_FILE)
    except SpeakerRegistryError as exc:
        return [Finding(SPEAKERS_FILE.as_posix(), 0, exc.rule)]
    return _located(
        root, lambda corpus: unregistered_labels(corpus, registry), "unregistered_speaker"
    )


def check_transcripts(root: Path, scratch: Path) -> list[Finding]:
    try:
        return transcripts.check_transcripts(root, README_FILE)
    except StonewallError:
        return [Finding(README_FILE.as_posix(), 0, "transcripts_unavailable")]


def check_unit(
    root: Path, scratch: Path, *, unit_tests: Sequence[str] = UNIT_TESTS
) -> list[Finding]:
    command = [sys.executable, "-B", "-m", "unittest", *unit_tests]
    try:
        completed = subprocess.run(
            command, cwd=root, env=_subprocess_env(root), capture_output=True,
            text=True, timeout=SUBPROCESS_TIMEOUT, check=False,
        )
    except subprocess.TimeoutExpired:
        return [Finding("tests", 0, "unit_timeout")]
    output = completed.stdout + "\n" + completed.stderr
    # Only an assertion failure names its test; an error is never proof.
    rules = set(_UNIT_FAILURE_RE.findall(output))
    if _UNIT_ERROR_RE.search(output):
        rules.add("unit_errored")
    if completed.returncode != 0 and not rules:
        rules.add("unit_crashed")
    return [Finding("tests", 0, rule) for rule in sorted(rules)]


CHECKS: tuple[Check, ...] = (
    Check("answers", check_answers),
    Check("boundary", check_boundary_files),
    Check("bundle", check_bundle),
    Check("corpus", check_corpus),
    Check("disclosure", check_disclosure),
    Check("speakers", check_speakers),
    Check("transcripts", check_transcripts),
    Check("unit", check_unit),
)


def _nonempty_string(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise CheckHarnessError(f"seeded defect field {key!r} must be a nonempty string")
    return value


def load_defects(
    path: Path,
    *,
    checks: Sequence[Check] = CHECKS,
    unit_tests: Sequence[str] = UNIT_TESTS,
    subprocess_checks: frozenset[str] = SUBPROCESS_CHECKS,
) -> tuple[SeededDefect, ...]:
    """Load seeded defects and refuse any that could not prove its check."""
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise CheckHarnessError("seeded defects file is unreadable") from exc
    version = raw.get("version")
    if set(raw) - {"defects", "version"} or type(version) is not int or version != 1:
        raise CheckHarnessError("seeded defects file must be version 1")
    entries = raw.get("defects")
    if not isinstance(entries, list) or not all(isinstance(e, dict) for e in entries):
        raise CheckHarnessError("seeded defects must be an array of tables")
    known = {check.name for check in checks}
    methods = {test.rsplit(".", 1)[-1] for test in unit_tests}
    defects: list[SeededDefect] = []
    for entry in entries:
        if set(entry) - _DEFECT_KEYS:
            raise CheckHarnessError("seeded defect has an unknown field")
        name, check, expect, op = (
            _nonempty_string(entry, key) for key in ("name", "check", "expect", "op")
        )
        relative = canonical_relative_path(entry.get("path"))
        if not _NAME_RE.fullmatch(name) or any(d.name == name for d in defects):
            raise CheckHarnessError(f"seeded defect name is invalid or duplicated: {name}")
        if check not in known:
            raise CheckHarnessError(f"seeded defect names an unknown check: {name}")
        if not _RULE_RE.fullmatch(expect):
            raise CheckHarnessError(f"seeded defect expects an invalid rule id: {name}")
        if op not in OPS:
            raise CheckHarnessError(f"seeded defect has an unknown op: {name}")
        if relative is None:
            raise CheckHarnessError(f"seeded defect path is not canonical: {name}")
        if relative.parts[0] == "src" and check not in subprocess_checks:
            raise CheckHarnessError(f"in-process check cannot see src/: {name}")
        if check == "unit" and expect not in methods:
            raise CheckHarnessError(f"unit defect expects an unknown test: {name}")
        old, new, parts = entry.get("old", ""), entry.get("new", ""), entry.get("parts", [])
        if not isinstance(parts, list) or not all(isinstance(part, str) for part in parts):
            raise CheckHarnessError(f"seeded defect parts must be a list of strings: {name}")
        if op == "replace":
            if not isinstance(old, str) or not old or not isinstance(new, str) or parts:
                raise CheckHarnessError(f"replace defect needs old and new: {name}")
        elif "old" in entry or "new" in entry or not "".join(parts):
            raise CheckHarnessError(f"{op} defect needs parts only: {name}")
        defects.append(
            SeededDefect(name, check, expect, op, relative, old, new, tuple(parts))
        )
    return tuple(defects)


def snapshot_tree(root: Path) -> dict[str, str]:
    """Map each file to '<sha256>:<mode>' and each directory, the root as '.',
    to 'dir:<mode>'.

    The mode is every permission bit in octal, so any chmod is a write.
    """
    snapshot: dict[str, str] = {}
    for current, dirnames, filenames in os.walk(root):
        base = Path(current)
        if base == root and ".git" in dirnames:
            dirnames.remove(".git")
        dirnames.sort()
        names = sorted(dirnames + filenames)
        bits = f"{stat.S_IMODE(base.lstat().st_mode):04o}"
        snapshot[base.relative_to(root).as_posix()] = f"dir:{bits}"
        for name in names:
            path = base / name
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                raise CheckHarnessError("tree contains a symlink")
            if name in filenames:
                if not stat.S_ISREG(mode):
                    raise CheckHarnessError("tree contains a non-regular file")
                bits = f"{stat.S_IMODE(mode):04o}"
                snapshot[path.relative_to(root).as_posix()] = f"{sha256_file(path)}:{bits}"
    return dict(sorted(snapshot.items()))


def stage_tree(repo_root: Path, destination: Path) -> None:
    """Copy exactly the publishable candidate set and make it a git tree."""
    destination.mkdir(parents=True, exist_ok=True)
    paths = candidate_paths(repo_root)
    for relative in paths:
        source = repo_root / relative
        if source.is_symlink() or not source.is_file():
            raise CheckHarnessError("staged files must be regular files")
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    # The index equals the source candidate set, so a tracked file that an
    # ignore rule matches stays a candidate in the staged copy too.
    listing = b"".join(path.as_posix().encode("utf-8") + b"\0" for path in paths)
    try:
        subprocess.run(
            ["git", "init", "-q"], cwd=destination, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "add", "-f", "--pathspec-from-file=-", "--pathspec-file-nul"],
            cwd=destination, input=listing, check=True, capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise CheckHarnessError("cannot initialise the staged copy") from exc


def apply_defect(root: Path, defect: SeededDefect) -> None:
    """Apply *defect*; one that no longer applies is an error, never a skip."""
    target = root / defect.path
    stale = CheckHarnessError(f"defect no longer applies: {defect.name}")
    if defect.op == "replace":
        if not target.is_file():
            raise stale
        text = target.read_bytes().decode("utf-8")
        if text.count(defect.old) != 1:
            raise stale
        target.write_bytes(text.replace(defect.old, defect.new).encode("utf-8"))
    elif defect.op == "write":
        if target.exists() or target.is_symlink():
            raise stale
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes("".join(defect.parts).encode("utf-8"))
    else:
        if not target.is_file():
            raise stale
        with target.open("ab") as handle:
            handle.write("".join(defect.parts).encode("utf-8"))


def render_registry(defects: Sequence[SeededDefect], checks: Sequence[Check] = CHECKS) -> str:
    """One row per defect, in check order then file order; runs nothing."""
    return "\n".join(
        f"{check.name:<12} {defect.name:<32} {defect.expect}"
        for check in checks
        for defect in defects
        if defect.check == check.name
    )


def _rules(findings: Iterable[Finding]) -> tuple[str, ...]:
    return tuple(sorted({finding.rule for finding in findings}))


def _changed(before: dict[str, str], after: dict[str, str]) -> tuple[str, ...]:
    return tuple(sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p)))


def _run_once(
    check: Check, staged: Path, work: Path, defect: SeededDefect | None
) -> tuple[tuple[Finding, ...], tuple[str, ...], bool]:
    """Run *check* on a fresh copy; return (findings, wrote, crashed)."""
    tree, scratch = work / "tree", work / "scratch"
    shutil.copytree(staged, tree, symlinks=True)
    scratch.mkdir()
    try:
        if defect is not None:
            apply_defect(tree, defect)
        before = snapshot_tree(tree)
        try:
            findings = tuple(sorted(set(check.run(tree, scratch))))
            crashed = False
        except Exception:  # noqa: BLE001 -- a crash is a result, never a pass
            findings, crashed = (Finding(check.name, 0, "check_crashed"),), True
        return findings, _changed(before, snapshot_tree(tree)), crashed
    finally:
        shutil.rmtree(work, ignore_errors=True)


def run_checks(
    repo_root: Path,
    *,
    defects_path: Path | None = None,
    only: Iterable[str] | None = None,
    checks: Sequence[Check] = CHECKS,
) -> CheckReport:
    """Run every check on the unmodified copy, then against each seeded defect."""
    defects = load_defects(defects_path or repo_root / DEFECTS_FILE, checks=checks)
    selected = tuple(checks)
    if only is not None:
        wanted = set(only)
        if wanted - {check.name for check in checks}:
            raise CheckHarnessError("unknown check requested")
        selected = tuple(check for check in checks if check.name in wanted)
    with tempfile.TemporaryDirectory(prefix="stonewall-checks-") as raw:
        base = Path(raw)
        staged = base / "staged"
        stage_tree(repo_root, staged)
        tree_sha256 = merkle_root(snapshot_tree(staged).items())
        clean: list[CheckOutcome] = []
        outcomes: list[DefectOutcome] = []
        runs = 0
        for check in selected:
            runs += 1
            found, wrote, _crashed = _run_once(check, staged, base / f"run{runs}", None)
            clean.append(CheckOutcome(check.name, _rules(found), wrote, found))
            for defect in (d for d in defects if d.check == check.name):
                runs += 1
                found, wrote, crashed = _run_once(check, staged, base / f"run{runs}", defect)
                rules = _rules(found)
                if wrote:
                    status = "wrote_tree"
                elif crashed:
                    status = "check_crashed"
                elif not rules:
                    status = "survived"
                elif defect.expect not in rules:
                    status = "wrong_reason"
                else:
                    status = "rejected"
                outcomes.append(
                    DefectOutcome(
                        defect.name, defect.check, defect.expect, status, rules, wrote, found
                    )
                )
    challenged = {outcome.check for outcome in outcomes}
    return CheckReport(
        tree_sha256=tree_sha256,
        clean=tuple(clean),
        defects=tuple(outcomes),
        unchallenged=tuple(c.name for c in selected if c.name not in challenged),
    )
