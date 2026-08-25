"""Fail-closed publication boundary for the public reference repository.

Reports contain rule identifiers and locations only. A matched value is never
included in an exception, log line, JSON result, or command exit message.
"""

from __future__ import annotations

import re
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from .compiler import compile_corpus
from .errors import PublicationBoundaryError, StonewallError
from .hashing import canonical_json_bytes, sha256_bytes


@dataclass(frozen=True, slots=True)
class BoundaryConfig:
    manifest_path: PurePosixPath
    reference_root: PurePosixPath
    allowed_email_domains: frozenset[str]
    allowed_exact_paths: frozenset[str]
    allowed_path_prefixes: tuple[str, ...]
    denied_exact_paths: frozenset[str]
    denied_path_prefixes: tuple[str, ...]
    denied_suffixes: frozenset[str]
    reference_metadata_fields: frozenset[str]


@dataclass(frozen=True, slots=True, order=True)
class Finding:
    path: str
    line: int
    rule: str

    def render(self) -> str:
        location = f"{self.path}:{self.line}" if self.line else self.path
        return f"[{self.rule}] {location}"


_EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@([A-Z0-9.-]+\.[A-Z]{2,})\b")
_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}(?!\d)"
)
_SSN_RE = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")
_USER_PATH_RE = re.compile(
    r"(?:/" + "Users/" + r"[^/\s]+|/" + "home/" + r"[^/\s]+|"
    r"[A-Za-z]:\\" + "Users\\" + r"[^\\\s]+)"
)
_ADDRESS_RE = re.compile(
    r"(?i)\b\d{1,6}\s+(?:[A-Z][a-z]+\s+){0,4}"
    r"(?:Street|St|Road|Rd|Avenue|Ave|Boulevard|Blvd|Drive|Dr|Lane|Ln|Court|Ct|"
    r"Terrace|Way|Place|Circle)\b"
)
_CREDENTIAL_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
)
_ASSIGNED_SECRET_RE = re.compile(
    r"(?ix)(?<![A-Z0-9_])"
    r"[\"']?(?:[A-Z0-9]+[_-])*"
    r"(?:api[_-]?key|client[_-]?secret|password|secret|token)[\"']?"
    r"(?![A-Z0-9_])\s*[:=]\s*"
    r"(?:[\"'](?P<quoted>[^\"'\n]{12,})[\"']|"
    r"(?P<bare>[^\s#,'\"}\]]{12,}))"
)
_PLACEHOLDER_PARTS = (
    "example",
    "placeholder",
    "replace_me",
    "your_",
    "${",
    "<",
    "xxx",
)
_NON_LITERAL_SECRET_PARTS = (
    "args.",
    "config.",
    "env.",
    "env[",
    "getenv(",
    "input(",
    "os.environ",
    "process.env",
    "secretmanager",
    "secrets.",
    "settings.",
)


def _require_string_list(raw: dict[str, Any], key: str) -> tuple[str, ...]:
    value = raw.get(key)
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise PublicationBoundaryError(f"config field {key!r} must be a string list")
    return tuple(value)


def _relative_config_path(value: Any, *, field: str) -> PurePosixPath:
    if not isinstance(value, str):
        raise PublicationBoundaryError(f"config field {field!r} must be a string")
    path = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise PublicationBoundaryError(f"config field {field!r} must be a canonical relative path")
    return path


def _resolve_repo_path(repo_root: Path, relative: PurePosixPath) -> Path:
    root = repo_root.resolve()
    candidate = root
    for part in relative.parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise PublicationBoundaryError("configured paths cannot use symlinks")
    candidate = candidate.resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise PublicationBoundaryError("configured path escapes repository root") from exc
    return candidate


def load_config(path: Path) -> BoundaryConfig:
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise PublicationBoundaryError("publication boundary config is unreadable") from exc
    if raw.get("version") != 1:
        raise PublicationBoundaryError("unsupported publication boundary config version")
    manifest_path = _relative_config_path(raw.get("manifest_path"), field="manifest_path")
    reference_root = _relative_config_path(raw.get("reference_root"), field="reference_root")
    return BoundaryConfig(
        manifest_path=manifest_path,
        reference_root=reference_root,
        allowed_email_domains=frozenset(
            value.casefold() for value in _require_string_list(raw, "allowed_email_domains")
        ),
        allowed_exact_paths=frozenset(_require_string_list(raw, "allowed_exact_paths")),
        allowed_path_prefixes=_require_string_list(raw, "allowed_path_prefixes"),
        denied_exact_paths=frozenset(_require_string_list(raw, "denied_exact_paths")),
        denied_path_prefixes=_require_string_list(raw, "denied_path_prefixes"),
        denied_suffixes=frozenset(
            value.casefold() for value in _require_string_list(raw, "denied_suffixes")
        ),
        reference_metadata_fields=frozenset(
            _require_string_list(raw, "reference_metadata_fields")
        ),
    )


def candidate_paths(repo_root: Path) -> tuple[PurePosixPath, ...]:
    """Enumerate staged/tracked and non-ignored candidate files NUL-safely."""
    try:
        completed = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=repo_root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise PublicationBoundaryError("cannot enumerate repository candidates") from exc
    paths: list[PurePosixPath] = []
    for raw in completed.stdout.split(b"\0"):
        if not raw:
            continue
        try:
            value = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise PublicationBoundaryError("repository contains a non-UTF-8 path") from exc
        relative = PurePosixPath(value)
        if relative.is_absolute() or ".." in relative.parts:
            raise PublicationBoundaryError("repository contains a noncanonical path")
        path = repo_root / relative
        if path.exists() or path.is_symlink():
            paths.append(relative)
    return tuple(sorted(set(paths), key=lambda item: item.as_posix()))


def _content_class(path: PurePosixPath, config: BoundaryConfig) -> str:
    value = path.as_posix()
    if value.startswith(config.reference_root.as_posix().rstrip("/") + "/"):
        return "coded_reference"
    if value.startswith("tests/"):
        return "test"
    if value.startswith("docs/") or value.endswith(".md"):
        return "documentation"
    if value.startswith(".github/workflows/"):
        return "workflow"
    if value.startswith(("src/", "scripts/")):
        return "source_code"
    return "configuration"


def build_manifest(
    repo_root: Path, paths: Iterable[PurePosixPath], config: BoundaryConfig
) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for relative in sorted(paths, key=lambda item: item.as_posix()):
        if relative == config.manifest_path:
            continue
        path = repo_root / relative
        if path.is_symlink():
            raise PublicationBoundaryError("publication manifest cannot include symlinks")
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise PublicationBoundaryError("publication candidate is unreadable") from exc
        value = relative.as_posix()
        generated_by = None
        if value.startswith(config.reference_root.as_posix().rstrip("/") + "/"):
            generated_by = "scripts/generate_sample_corpus.py"
        entries.append(
            {
                "path": value,
                "sha256": sha256_bytes(content),
                "size": len(content),
                "executable": bool(path.stat().st_mode & 0o111),
                "content_class": _content_class(relative, config),
                "generated_by": generated_by,
                "destination": "public_repository",
            }
        )
    return {"schema_version": 1, "path_count": len(entries), "entries": entries}


def write_manifest(repo_root: Path, config: BoundaryConfig) -> dict[str, Any]:
    paths = candidate_paths(repo_root)
    payload = build_manifest(repo_root, paths, config)
    destination = _resolve_repo_path(repo_root, config.manifest_path)
    destination.write_bytes(canonical_json_bytes(payload))
    return payload


def _line_findings(path: str, text: str, config: BoundaryConfig) -> list[Finding]:
    findings: list[Finding] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for match in _EMAIL_RE.finditer(line):
            if match.group(1).casefold() not in config.allowed_email_domains:
                findings.append(Finding(path, line_number, "email_address"))
        if _PHONE_RE.search(line):
            findings.append(Finding(path, line_number, "phone_number"))
        if _SSN_RE.search(line):
            findings.append(Finding(path, line_number, "ssn_shape"))
        for match in _USER_PATH_RE.finditer(line):
            value = match.group(0).casefold()
            if not any(part in value for part in ("<username>", "yourname", "example", "testuser")):
                findings.append(Finding(path, line_number, "absolute_user_path"))
        if _ADDRESS_RE.search(line):
            findings.append(Finding(path, line_number, "street_address"))
        if any(pattern.search(line) for pattern in _CREDENTIAL_PATTERNS):
            findings.append(Finding(path, line_number, "credential_shape"))
        for match in _ASSIGNED_SECRET_RE.finditer(line):
            value = (match.group("quoted") or match.group("bare") or "").casefold()
            if not any(part in value for part in _PLACEHOLDER_PARTS) and not any(
                part in value for part in _NON_LITERAL_SECRET_PARTS
            ):
                findings.append(Finding(path, line_number, "assigned_secret"))
    return findings


def scan_path(
    repo_root: Path, relative: PurePosixPath, config: BoundaryConfig
) -> list[Finding]:
    value = relative.as_posix()
    path_rules = sorted(
        {finding.rule for finding in _line_findings("candidate", value, config)}
    )
    report_path = value
    if path_rules:
        report_path = f"candidate:{sha256_bytes(value.encode('utf-8'))[:12]}"
    findings: list[Finding] = []
    findings.extend(Finding(report_path, 0, rule) for rule in path_rules)
    if value not in config.allowed_exact_paths and not any(
        value.startswith(prefix) for prefix in config.allowed_path_prefixes
    ):
        findings.append(Finding(report_path, 0, "unapproved_path"))
    if value in config.denied_exact_paths:
        findings.append(Finding(report_path, 0, "denied_path"))
    if any(value.startswith(prefix) for prefix in config.denied_path_prefixes):
        findings.append(Finding(report_path, 0, "denied_path_prefix"))
    if relative.suffix.casefold() in config.denied_suffixes:
        findings.append(Finding(report_path, 0, "denied_file_type"))
    path = repo_root / relative
    if path.is_symlink():
        findings.append(Finding(report_path, 0, "symlink"))
        return findings
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise PublicationBoundaryError("publication candidate is unreadable") from exc
    if b"\0" in raw:
        findings.append(Finding(report_path, 0, "binary_content"))
        return findings
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PublicationBoundaryError("publication candidate is not UTF-8") from exc
    findings.extend(_line_findings(report_path, text, config))
    return findings


def validate_reference_contract(repo_root: Path, config: BoundaryConfig) -> list[Finding]:
    reference_root = _resolve_repo_path(repo_root, config.reference_root)
    try:
        corpus = compile_corpus(reference_root)
    except StonewallError:
        return [
            Finding(config.reference_root.as_posix(), 0, "reference_contract_invalid")
        ]
    findings: list[Finding] = []
    for artifact in corpus.artifacts:
        keys = set(artifact.metadata)
        for key in sorted(keys - config.reference_metadata_fields):
            findings.append(
                Finding(
                    (config.reference_root / artifact.path).as_posix(),
                    1,
                    "unknown_reference_field",
                )
            )
    return findings


def check_boundary(repo_root: Path, config: BoundaryConfig) -> list[Finding]:
    paths = candidate_paths(repo_root)
    findings = [
        finding
        for relative in paths
        for finding in scan_path(repo_root, relative, config)
    ]
    findings.extend(validate_reference_contract(repo_root, config))
    manifest_path = repo_root / config.manifest_path
    expected = build_manifest(repo_root, paths, config)
    try:
        actual = manifest_path.read_bytes()
    except OSError:
        findings.append(Finding(config.manifest_path.as_posix(), 0, "manifest_missing"))
    else:
        if actual != canonical_json_bytes(expected):
            findings.append(Finding(config.manifest_path.as_posix(), 0, "manifest_drift"))
    return sorted(set(findings))
