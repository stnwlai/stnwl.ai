"""README transcripts: console blocks regenerated from the commands they show.

A transcript block opens with a line that is exactly '```console', closes with
a line that is exactly '```', and starts with '$ <command>'. Only a few
read-only commands may appear, and they run in-process from the repository
root, so the output is deterministic and independent of the hash seed. A file
a command reads must be in the publishable candidate set.

Publishability is checked before drift: a block whose rendered output or
written body contains a whole body line of a record the publish channel may
not carry is refused and never written. Findings carry the document path, the
block line and a rule id, never block text.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shlex
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .compiler import compile_corpus
from .disclosure import load_policy, unpublishable_lines
from .errors import PublicationBoundaryError, StonewallError, TranscriptError
from .layout import CORPUS_DIR, POLICY_FILE, canonical_relative_path
from .models import Finding
from .publication import candidate_paths
from .text import collapse_whitespace

ALLOWED_SUBCOMMANDS = frozenset({"audit-answer", "cite", "packet"})
_FENCE = "```"
_OPEN = "```console"
_SHELL_CHARACTERS = frozenset("|&;<>`$\n")
# Subcommand -> argument destinations that name a file the command reads.
_PATH_ARGUMENTS = {"audit-answer": ("path",)}
# JSON escapes of whitespace; matched as spaces so an escaped tab still collapses.
_JSON_SPACE_RE = re.compile(r"\\(?:[bfnrt]|u00(?:0[bB]|1[c-fC-F]))")


@dataclass(frozen=True, slots=True)
class TranscriptBlock:
    line: int  # 1-based line of the opening fence
    command: str
    body: str  # block content including its final newline
    start: int  # character offsets of the content, for rewriting
    end: int


def parse_transcripts(text: str) -> tuple[TranscriptBlock, ...]:
    """Find every console block; an unclosed fence is an error, never a skip."""
    if "\r" in text:
        number = text.count("\n", 0, text.index("\r")) + 1
        raise TranscriptError("transcript_unsupported", "LF line endings required", line=number)
    blocks: list[TranscriptBlock] = []
    lines = text.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    index = 0
    while index < len(lines):
        fence = lines[index].rstrip("\n")
        index += 1
        if not fence.startswith(_FENCE):
            continue
        close = next(
            (i for i in range(index, len(lines)) if lines[i].rstrip("\n") == _FENCE), None
        )
        if close is None:
            raise TranscriptError("transcript_unterminated", line=index)
        opened, index = index, close + 1
        if fence != _OPEN:
            continue
        body = text[offsets[opened] : offsets[close]]
        if not body.startswith("$ ") or not body.endswith("\n"):
            raise TranscriptError("transcript_unsupported", line=opened)
        command = body.split("\n", 1)[0][2:]
        blocks.append(TranscriptBlock(opened, command, body, offsets[opened], offsets[close]))
    return tuple(blocks)


def publishable_file(repo_root: Path, value: str) -> Path:
    """The file *value* names, if it is canonical, symlink-free and publishable."""
    path = canonical_relative_path(value)
    if path is None:
        raise TranscriptError("transcript_unsupported", "path is not canonical")
    current = repo_root
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            raise TranscriptError("transcript_unsupported", "path uses a symlink")
    if not current.is_file():
        raise TranscriptError("transcript_unsupported", "path is not a regular file")
    try:
        candidates = candidate_paths(repo_root)
    except PublicationBoundaryError as exc:
        raise TranscriptError("transcripts_unavailable") from exc
    if path not in candidates:
        raise TranscriptError("transcript_unsupported", "path is not publishable")
    return current


def _path_arguments(tokens: list[str]) -> list[str]:
    """Raw file arguments of a stonewall command; none when it will not parse."""
    from . import cli  # lazy: the command surface imports this module

    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        try:
            args = cli.build_parser().parse_args(tokens[1:])
        except SystemExit:
            return []  # the command reports its own usage error and reads nothing
    return [getattr(args, dest) for dest in _PATH_ARGUMENTS.get(args.command, ())]


def render_command(repo_root: Path, command: str) -> str:
    """Run one allowed command in-process and return its transcript text."""
    unsupported = TranscriptError("transcript_unsupported")
    if _SHELL_CHARACTERS & set(command):
        raise unsupported
    try:
        tokens = shlex.split(command)
    except ValueError as exc:
        raise unsupported from exc
    if len(tokens) == 2 and tokens[0] == "cat":
        try:
            output = publishable_file(repo_root, tokens[1]).read_bytes().decode("utf-8")
        except UnicodeDecodeError as exc:
            raise unsupported from exc
        code = 0
    elif tokens[:1] == ["stonewall"] and (
        tokens[1:] == ["checks", "--list"]
        or (len(tokens) > 1 and tokens[1] in ALLOWED_SUBCOMMANDS)
    ):
        from . import cli  # lazy: the command surface imports this module

        for value in _path_arguments(tokens):
            publishable_file(repo_root, value)
        out, err = io.StringIO(), io.StringIO()
        with (
            contextlib.chdir(repo_root),
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
        ):
            try:
                code = cli.main(tokens[1:])
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else 1
        output = out.getvalue() + err.getvalue()
    else:
        raise unsupported
    if output and not output.endswith("\n"):
        output += "\n"
    return f"$ {command}\n{output}" + (f"[exit {code}]\n" if code else "")


def _unpublishable(repo_root: Path) -> tuple[str, ...]:
    try:
        corpus = compile_corpus(repo_root / CORPUS_DIR)
        policy = load_policy(repo_root / POLICY_FILE)
    except StonewallError as exc:
        raise TranscriptError("transcripts_unavailable") from exc
    lines = {text for _artifact_id, text in unpublishable_lines(corpus, policy)}
    forms = {_normalized(text) for text in lines} | {
        _normalized(json.dumps(text, ensure_ascii=False)[1:-1]) for text in lines
    }
    return tuple(sorted(forms))


def _normalized(text: str) -> str:
    return collapse_whitespace(_JSON_SPACE_RE.sub(" ", text))


def _carries(needles: tuple[str, ...], *texts: str) -> bool:
    return any(needle in _normalized(text) for text in texts for needle in needles)


def _read(repo_root: Path, document: PurePosixPath) -> str:
    try:
        return (repo_root / document).read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise TranscriptError("transcripts_unavailable") from exc


def check_transcripts(repo_root: Path, document: PurePosixPath) -> list[Finding]:
    """Findings for every block that is unpublishable, unsupported, or drifted."""
    location = document.as_posix()
    try:
        needles = _unpublishable(repo_root)
        blocks = parse_transcripts(_read(repo_root, document))
    except TranscriptError as exc:
        return [Finding(location, exc.line, exc.rule)]
    findings: list[Finding] = []
    for block in blocks:
        try:
            rendered = render_command(repo_root, block.command)
        except TranscriptError as exc:
            findings.append(Finding(location, block.line, exc.rule))
            continue
        if _carries(needles, rendered, block.body):
            findings.append(Finding(location, block.line, "transcript_unpublishable"))
        elif rendered != block.body:
            findings.append(Finding(location, block.line, "transcript_drift"))
    return sorted(findings)


def write_transcripts(repo_root: Path, document: PurePosixPath) -> int:
    """Rewrite drifted blocks atomically; refuse to write anything otherwise unsafe."""
    needles = _unpublishable(repo_root)
    target = repo_root / document
    text = _read(repo_root, document)
    replacements: list[tuple[TranscriptBlock, str]] = []
    for block in parse_transcripts(text):
        try:
            rendered = render_command(repo_root, block.command)
        except TranscriptError as exc:
            raise TranscriptError(exc.rule, line=block.line) from exc
        if _carries(needles, rendered, block.body):
            raise TranscriptError("transcript_unpublishable", line=block.line)
        if rendered != block.body:
            replacements.append((block, rendered))
    if not replacements:
        return 0
    for block, rendered in reversed(replacements):
        text = text[: block.start] + rendered + text[block.end :]
    handle, raw = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    temporary = Path(raw)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(text.encode("utf-8"))
        os.chmod(temporary, stat.S_IMODE(os.stat(target).st_mode))
        os.replace(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return len(replacements)
