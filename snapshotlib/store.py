"""Snapshot storage: atomic writes, locking, verification, update journal."""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import re
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

from .diff import diff
from .errors import (
    SnapshotConcurrentModificationError,
    SnapshotCorruptError,
    SnapshotMismatchError,
    SnapshotMissingError,
    SnapshotTamperedError,
)
from .serialize import canonical_str

FORMAT_VERSION = 1
_NAME_RE = re.compile(r"[A-Za-z0-9_.-]+$")

# In-process locks, so threads of one process are also serialized
# (fcntl.flock alone does not exclude threads of the same process).
_thread_locks: dict = {}
_thread_locks_guard = threading.Lock()


def _thread_lock_for(key: str) -> threading.Lock:
    with _thread_locks_guard:
        return _thread_locks.setdefault(key, threading.Lock())


class SnapshotResult:
    def __init__(self, name, status, entries=None):
        self.name = name
        self.status = status  # "created" | "matched" | "updated"
        self.entries = entries or []

    def __repr__(self):
        return f"SnapshotResult(name={self.name!r}, status={self.status!r})"


class SnapshotStore:
    """Stores snapshots as <directory>/<name>.snap.json files.

    File format (JSON, pretty-printed for humans):
        {"format": 1, "algorithm": "sha256",
         "digest": "<sha256 of payload>",
         "payload": "<canonical single-line JSON of the value>"}

    Every update is journaled to <directory>/<name>.updates.jsonl with the
    old payload, the new payload and the structured diff between them.
    """

    def __init__(self, directory, update=None):
        self.directory = Path(directory)
        if update is None:
            update = os.environ.get("SNAPSHOT_UPDATE", "").lower() in ("1", "true", "yes")
        self.update = bool(update)

    # -- public API ---------------------------------------------------------

    def assert_snapshot(self, name, value, update=None, create=True) -> SnapshotResult:
        """First run writes the snapshot; later runs compare against it.

        update=True  -> overwrite the snapshot and journal the old/new diff.
        create=False -> raise SnapshotMissingError instead of creating.
        """
        self._validate_name(name)
        if update is None:
            update = self.update
        payload = canonical_str(value)
        path = self._snap_path(name)
        with self._locked(name):
            if not path.exists():
                if not create:
                    raise SnapshotMissingError(
                        f"snapshot missing: {path} (run without create=False, "
                        "or with SNAPSHOT_UPDATE=1, to create it)"
                    )
                self._atomic_write(path, self._make_record(payload))
                return SnapshotResult(name, "created")

            record = self._read_record(path)
            if record["payload"] == payload:
                return SnapshotResult(name, "matched")

            entries = diff(json.loads(record["payload"]), json.loads(payload))
            if not update:
                raise SnapshotMismatchError(name, entries, path)

            # Hook for tests / subclasses: runs inside the lock, after read.
            self._after_read(path)

            # Refuse to silently overwrite a file that changed under us.
            current = self._read_record(path)
            if current["digest"] != record["digest"]:
                raise SnapshotConcurrentModificationError(
                    f"snapshot changed concurrently: {path} "
                    f"(read digest {record['digest'][:12]}..., "
                    f"now {current['digest'][:12]}...); refusing to overwrite"
                )
            self._write_update(path, name, record, payload, entries)
            return SnapshotResult(name, "updated", entries)

    def read(self, name):
        """Return the stored (normalized) value, with full verification."""
        self._validate_name(name)
        with self._locked(name):
            return json.loads(self._read_record(self._snap_path(name))["payload"])

    # -- internals ----------------------------------------------------------

    def _after_read(self, path):
        """No-op hook invoked inside the lock after reading; used by tests."""

    @staticmethod
    def _validate_name(name):
        if not name or not _NAME_RE.match(name):
            raise ValueError(f"invalid snapshot name: {name!r}")

    def _snap_path(self, name) -> Path:
        return self.directory / f"{name}.snap.json"

    def _journal_path(self, name) -> Path:
        return self.directory / f"{name}.updates.jsonl"

    @contextlib.contextmanager
    def _locked(self, name):
        self.directory.mkdir(parents=True, exist_ok=True)
        lock_path = self.directory / f"{name}.lock"
        thread_lock = _thread_lock_for(str(lock_path.resolve()))
        with thread_lock:
            with open(lock_path, "a+b") as handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _make_record(payload: str) -> bytes:
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        body = {
            "format": FORMAT_VERSION,
            "algorithm": "sha256",
            "digest": digest,
            "payload": payload,
        }
        return (json.dumps(body, indent=2, ensure_ascii=False) + "\n").encode("utf-8")

    def _read_record(self, path: Path) -> dict:
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            raise SnapshotMissingError(f"snapshot missing: {path}") from None
        try:
            record = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SnapshotCorruptError(f"snapshot corrupt: {path}: {exc}") from None
        if (
            not isinstance(record, dict)
            or record.get("format") != FORMAT_VERSION
            or not isinstance(record.get("digest"), str)
            or not isinstance(record.get("payload"), str)
        ):
            raise SnapshotCorruptError(
                f"snapshot corrupt: {path}: missing or invalid header fields"
            )
        actual = hashlib.sha256(record["payload"].encode("utf-8")).hexdigest()
        if actual != record["digest"]:
            raise SnapshotTamperedError(
                f"snapshot tampered: {path}: payload does not match stored digest "
                "(file was modified outside the framework?)"
            )
        return record

    @staticmethod
    def _atomic_write(path: Path, data: bytes) -> None:
        """Write via temp file + os.replace: readers never see a half file."""
        fd, tmp = tempfile.mkstemp(
            dir=str(path.parent), prefix=path.name + ".", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def _write_update(self, path, name, old_record, new_payload, entries) -> None:
        new_record = self._make_record(new_payload)
        self._atomic_write(path, new_record)
        journal_entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "snapshot": name,
            "old_digest": old_record["digest"],
            "new_digest": json.loads(new_record)["digest"],
            "diff": entries,
            "old": old_record["payload"],
            "new": new_payload,
        }
        with open(self._journal_path(name), "a", encoding="utf-8") as handle:
            handle.write(json.dumps(journal_entry, ensure_ascii=False) + "\n")
