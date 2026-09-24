"""Distinguishable error types for every snapshot failure mode."""
from __future__ import annotations


class SnapshotError(Exception):
    """Base class for all snapshot errors."""


class SnapshotMissingError(SnapshotError):
    """The snapshot file does not exist (and creation was not allowed)."""


class SnapshotCorruptError(SnapshotError):
    """The snapshot file is not parseable or misses required header fields."""


class SnapshotTamperedError(SnapshotCorruptError):
    """The file parses, but the payload digest does not match the header.

    This is the signature of a manual (out-of-framework) edit.
    """


class SnapshotMismatchError(SnapshotError):
    """The value does not match the stored snapshot."""

    def __init__(self, name, entries, path):
        self.name = name
        self.entries = entries
        self.path = path
        super().__init__(self.report())

    def report(self) -> str:
        from .diff import format_report

        return format_report(self.entries, header=f"snapshot mismatch: {self.name} ({self.path})")


class SnapshotConcurrentModificationError(SnapshotError):
    """The snapshot file changed between reading and writing it.

    Raised when a conflicting writer (another process, or a manual edit)
    modified the file underneath us; nothing was overwritten silently.
    """
