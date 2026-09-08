"""Custom errors with stable machine-readable metadata."""

from dataclasses import dataclass, field


@dataclass(slots=True)
class CliError(Exception):
    """Known CLI failure with a stable exit code."""

    error: str
    code: str
    exit_code: int
    details: dict = field(default_factory=dict)
