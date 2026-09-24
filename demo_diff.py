"""Print a sample mismatch report and the update journal entry.

Run: python3 demo_diff.py
"""
import json
import tempfile
from pathlib import Path

from snapshotlib import SnapshotMismatchError, SnapshotStore

old_value = {
    "user": {"name": "ada", "roles": ["admin", "dev"], "score": 0.1 + 0.2},
    "tags": {"python", "testing", "snapshot"},
    "bio": "a very long biography " * 12,
}
new_value = {
    "user": {"name": "ada", "roles": ["admin", "dev", "ops"], "score": 0.3},
    "tags": {"python", "snapshot"},
    "bio": "a very long biography " * 11 + "a very long obituary  ",
    "extra": True,
}

with tempfile.TemporaryDirectory() as directory:
    store = SnapshotStore(directory)
    store.assert_snapshot("user_profile", old_value)

    print("=== 1. mismatch report (assert fails) ===")
    try:
        store.assert_snapshot("user_profile", new_value)
    except SnapshotMismatchError as exc:
        print(exc.report())

    print()
    print("=== 2. explicit update leaves an old/new diff record ===")
    result = store.assert_snapshot("user_profile", new_value, update=True)
    print(f"status: {result.status}")
    journal = Path(directory, "user_profile.updates.jsonl").read_text().strip()
    entry = json.loads(journal)
    print(f"journal file: user_profile.updates.jsonl")
    print(f"  old_digest: {entry['old_digest'][:16]}...")
    print(f"  new_digest: {entry['new_digest'][:16]}...")
    print(f"  diff entries recorded: {len(entry['diff'])}")
    print(f"  old payload kept: {entry['old'][:60]}...")
    print(f"  new payload kept: {entry['new'][:60]}...")
