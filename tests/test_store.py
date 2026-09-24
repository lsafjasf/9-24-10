import json
import tempfile
import unittest
from pathlib import Path

from snapshotlib import (
    SnapshotConcurrentModificationError,
    SnapshotCorruptError,
    SnapshotMismatchError,
    SnapshotMissingError,
    SnapshotStore,
    SnapshotTamperedError,
    canonical_str,
)


class StoreTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.store = SnapshotStore(self.dir)

    def snap_file(self, name="case"):
        return self.dir / f"{name}.snap.json"


class BasicFlowTests(StoreTestCase):
    def test_first_run_creates_then_matches(self):
        result = self.store.assert_snapshot("case", {"a": 1})
        self.assertEqual(result.status, "created")
        self.assertTrue(self.snap_file().exists())
        result = self.store.assert_snapshot("case", {"a": 1})
        self.assertEqual(result.status, "matched")

    def test_mismatch_raises_with_structured_diff(self):
        self.store.assert_snapshot("case", {"a": 1, "b": [1, 2]})
        with self.assertRaises(SnapshotMismatchError) as ctx:
            self.store.assert_snapshot("case", {"a": 1, "b": [1, 3]})
        entries = ctx.exception.entries
        self.assertEqual(entries[0]["path"], "$.b[1]")
        self.assertIn("$.b[1]", str(ctx.exception))

    def test_explicit_update_rewrites_and_journals(self):
        self.store.assert_snapshot("case", {"v": 1})
        result = self.store.assert_snapshot("case", {"v": 2}, update=True)
        self.assertEqual(result.status, "updated")
        # New value now matches.
        self.assertEqual(self.store.assert_snapshot("case", {"v": 2}).status, "matched")
        # Journal records old, new and the diff.
        journal = (self.dir / "case.updates.jsonl").read_text().strip().splitlines()
        self.assertEqual(len(journal), 1)
        entry = json.loads(journal[0])
        self.assertEqual(json.loads(entry["old"]), {"v": 1})
        self.assertEqual(json.loads(entry["new"]), {"v": 2})
        self.assertEqual(entry["diff"][0]["path"], "$.v")
        self.assertNotEqual(entry["old_digest"], entry["new_digest"])

    def test_env_var_enables_update(self):
        import os

        self.store.assert_snapshot("case", {"v": 1})
        os.environ["SNAPSHOT_UPDATE"] = "1"
        try:
            store = SnapshotStore(self.dir)
            self.assertEqual(store.assert_snapshot("case", {"v": 9}).status, "updated")
        finally:
            del os.environ["SNAPSHOT_UPDATE"]


class DistinguishableStateTests(StoreTestCase):
    def test_missing(self):
        with self.assertRaises(SnapshotMissingError) as ctx:
            self.store.assert_snapshot("nope", {"v": 1}, create=False)
        self.assertIn("missing", str(ctx.exception))

    def test_corrupt_unparseable(self):
        self.snap_file().write_bytes(b"{not json at all")
        with self.assertRaises(SnapshotCorruptError) as ctx:
            self.store.assert_snapshot("case", {"v": 1})
        self.assertIn("corrupt", str(ctx.exception))
        self.assertNotIsInstance(ctx.exception, SnapshotTamperedError)

    def test_corrupt_missing_fields(self):
        self.snap_file().write_text('{"format": 1}')
        with self.assertRaises(SnapshotCorruptError):
            self.store.assert_snapshot("case", {"v": 1})

    def test_tampered_manual_edit(self):
        self.store.assert_snapshot("case", {"v": 1})
        # Simulate a hand edit: valid JSON, but digest no longer matches.
        record = json.loads(self.snap_file().read_text())
        record["payload"] = canonical_str({"v": 999})
        self.snap_file().write_text(json.dumps(record, indent=2))
        with self.assertRaises(SnapshotTamperedError) as ctx:
            self.store.assert_snapshot("case", {"v": 1})
        self.assertIn("tampered", str(ctx.exception))

    def test_concurrent_modification_detected(self):
        self.store.assert_snapshot("case", {"v": 1})

        store = SnapshotStore(self.dir, update=True)
        path = self.snap_file()

        def evil_rewrite(_path):
            # Someone rewrites the file between our read and our write.
            record = json.loads(path.read_text())
            record["payload"] = canonical_str({"v": "sneaky"})
            record["digest"] = __import__("hashlib").sha256(
                record["payload"].encode()
            ).hexdigest()
            path.write_text(json.dumps(record, indent=2))

        store._after_read = evil_rewrite
        with self.assertRaises(SnapshotConcurrentModificationError) as ctx:
            store.assert_snapshot("case", {"v": 2})
        self.assertIn("concurrently", str(ctx.exception))
        # The sneaky write was NOT silently overwritten.
        self.assertEqual(json.loads(path.read_text())["payload"],
                         canonical_str({"v": "sneaky"}))


class FileFormatTests(StoreTestCase):
    def test_snapshot_file_is_self_verifying(self):
        self.store.assert_snapshot("case", {"b": {1, 2}, "a": 0.5})
        record = json.loads(self.snap_file().read_text())
        self.assertEqual(record["format"], 1)
        self.assertEqual(record["algorithm"], "sha256")
        import hashlib

        self.assertEqual(
            record["digest"],
            hashlib.sha256(record["payload"].encode()).hexdigest(),
        )

    def test_invalid_name_rejected(self):
        with self.assertRaises(ValueError):
            self.store.assert_snapshot("../escape", {"v": 1})


if __name__ == "__main__":
    unittest.main()
