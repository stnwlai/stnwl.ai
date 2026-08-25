"""Typed failures shared by the evidence compiler and its command surface."""


class StonewallError(Exception):
    """Base class for failures that should produce a concise CLI message."""


class FrontMatterError(StonewallError):
    """A source document does not satisfy the front-matter contract."""


class CorpusValidationError(StonewallError):
    """The corpus cannot be compiled without violating an invariant."""


class CitationVerificationError(StonewallError):
    """A citation no longer resolves to the bytes it originally addressed."""


class PublicationBoundaryError(StonewallError):
    """A tracked path or value is outside the public repository contract."""
