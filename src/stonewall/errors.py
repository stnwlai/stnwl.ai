"""Typed failures shared by the evidence compiler and its command surface."""


class StonewallError(Exception):
    """Base class for failures that should produce a concise CLI message."""


class FrontMatterError(StonewallError):
    """A source document does not satisfy the front-matter contract."""


class CorpusValidationError(StonewallError):
    """The corpus cannot be compiled without violating an invariant.

    str() is the message; ``rule`` names the invariant for check reports.
    """

    def __init__(self, message: str, *, rule: str = "corpus_invalid") -> None:
        super().__init__(message)
        self.rule = rule


class CitationVerificationError(StonewallError):
    """A citation no longer resolves to the bytes it originally addressed."""


class PublicationBoundaryError(StonewallError):
    """A tracked path or value is outside the public repository contract."""


class RuleError(StonewallError):
    """A failure that carries a stable rule id; str() is '<rule>: <detail>'."""

    def __init__(self, rule: str, detail: str = "") -> None:
        super().__init__(f"{rule}: {detail}" if detail else rule)
        self.rule = rule
        self.detail = detail


class DisclosureError(RuleError):
    """A disclosure policy is invalid, or a view or decision cannot be made."""


class SpeakerRegistryError(RuleError):
    """A speaker registry does not satisfy its contract."""


class AnswerError(StonewallError):
    """An answer document or evidence packet request is malformed."""


class CheckHarnessError(StonewallError):
    """The check harness or its seeded defects are misconfigured."""


class TranscriptError(RuleError):
    """A command transcript cannot be rendered or compared."""

    def __init__(self, rule: str, detail: str = "", *, line: int = 0) -> None:
        super().__init__(rule, detail)
        self.line = line
