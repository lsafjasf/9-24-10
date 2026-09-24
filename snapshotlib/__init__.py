"""A deterministic, concurrency-safe snapshot testing library (stdlib only)."""
from .diff import diff, format_report, preview
from .errors import (
    SnapshotConcurrentModificationError,
    SnapshotCorruptError,
    SnapshotError,
    SnapshotMismatchError,
    SnapshotMissingError,
    SnapshotTamperedError,
)
from .serialize import canonical_bytes, canonical_str, normalize
from .store import SnapshotResult, SnapshotStore

__all__ = [
    "SnapshotStore",
    "SnapshotResult",
    "SnapshotError",
    "SnapshotMissingError",
    "SnapshotCorruptError",
    "SnapshotTamperedError",
    "SnapshotMismatchError",
    "SnapshotConcurrentModificationError",
    "canonical_str",
    "canonical_bytes",
    "normalize",
    "diff",
    "format_report",
    "preview",
]
