"""Parallel writers must never produce half-written or silently lost files."""
import json
import multiprocessing as mp
import tempfile
import threading
import unittest
from pathlib import Path

from snapshotlib import (
    SnapshotConcurrentModificationError,
    SnapshotMismatchError,
    SnapshotStore,
    canonical_str,
)

WORKERS = 8


def _assert_worker(directory, name, value, update, queue):
    try:
        result = SnapshotStore(directory).assert_snapshot(name, value, update=update)
        queue.put(("ok", result.status))
    except Exception as exc:  # noqa: BLE001 - report exact type to parent
        queue.put(("error", type(exc).__name__))


def _run_parallel(directory, jobs):
    ctx = mp.get_context("fork")
    queue = ctx.Queue()
    procs = [
        ctx.Process(target=_assert_worker, args=(directory, name, value, update, queue))
        for name, value, update in jobs
    ]
    for proc in procs:
        proc.start()
    outcomes = [queue.get(timeout=60) for _ in procs]
    for proc in procs:
        proc.join(timeout=60)
        assert proc.exitcode == 0, f"worker crashed: exitcode={proc.exitcode}"
    return outcomes


def _valid_snapshot_payloads(directory):
    payloads = {}
    for path in Path(directory).glob("*.snap.json"):
        record = json.loads(path.read_text())  # raises if half-written
        import hashlib

        assert hashlib.sha256(record["payload"].encode()).hexdigest() == record["digest"]
        payloads[path.stem.replace(".snap", "")] = record["payload"]
    return payloads


class ConcurrentCreateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = self.tmp.name

    def test_distinct_names_all_succeed(self):
        jobs = [(f"case_{i}", {"worker": i}, False) for i in range(WORKERS)]
        outcomes = _run_parallel(self.dir, jobs)
        self.assertEqual(outcomes, [("ok", "created")] * WORKERS)
        payloads = _valid_snapshot_payloads(self.dir)
        self.assertEqual(len(payloads), WORKERS)
        for i in range(WORKERS):
            self.assertEqual(payloads[f"case_{i}"], canonical_str({"worker": i}))

    def test_same_name_conflicting_values_no_silent_loss(self):
        jobs = [("shared", {"worker": i}, False) for i in range(WORKERS)]
        outcomes = _run_parallel(self.dir, jobs)
        created = [o for o in outcomes if o == ("ok", "created")]
        matched = [o for o in outcomes if o == ("ok", "matched")]
        errors = [o for o in outcomes if o[0] == "error"]
        # Exactly one writer wins; everyone else gets an explicit error
        # (mismatch or concurrent-modification), never silent data loss.
        self.assertEqual(len(created), 1)
        self.assertEqual(len(matched), 0)
        self.assertEqual(len(errors), WORKERS - 1)
        for _, kind in errors:
            self.assertIn(
                kind,
                ("SnapshotMismatchError", "SnapshotConcurrentModificationError"),
            )
        # The surviving file is byte-identical to exactly one loser's value.
        payloads = _valid_snapshot_payloads(self.dir)
        valid = {canonical_str({"worker": i}) for i in range(WORKERS)}
        self.assertIn(payloads["shared"], valid)

    def test_same_name_same_value_is_benign(self):
        jobs = [("shared", {"v": 42}, False) for _ in range(WORKERS)]
        outcomes = _run_parallel(self.dir, jobs)
        statuses = sorted(outcomes)
        self.assertEqual(statuses.count(("ok", "created")), 1)
        self.assertEqual(statuses.count(("ok", "matched")), WORKERS - 1)

    def test_concurrent_updates_are_serialized_and_journaled(self):
        SnapshotStore(self.dir).assert_snapshot("shared", {"v": "base"})
        jobs = [("shared", {"v": f"worker-{i}"}, True) for i in range(WORKERS)]
        outcomes = _run_parallel(self.dir, jobs)
        self.assertEqual(outcomes, [("ok", "updated")] * WORKERS)
        # Final content is exactly one worker's value; file is valid.
        payloads = _valid_snapshot_payloads(self.dir)
        valid = {canonical_str({"v": f"worker-{i}"}) for i in range(WORKERS)}
        self.assertIn(payloads["shared"], valid)
        # Every update left a journal record: nothing was lost silently.
        journal = Path(self.dir, "shared.updates.jsonl").read_text().strip().splitlines()
        self.assertEqual(len(journal), WORKERS)
        digests = {json.loads(line)["new_digest"] for line in journal}
        self.assertEqual(len(digests), WORKERS)


class ThreadedWriteTests(unittest.TestCase):
    def test_threads_in_one_process_are_serialized(self):
        with tempfile.TemporaryDirectory() as directory:
            errors = []

            def work(i):
                try:
                    SnapshotStore(directory).assert_snapshot(f"t_{i % 4}", {"i": i % 4})
                except Exception as exc:  # noqa: BLE001
                    errors.append(exc)

            threads = [threading.Thread(target=work, args=(i,)) for i in range(32)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertEqual(errors, [])
            self.assertEqual(len(_valid_snapshot_payloads(directory)), 4)


if __name__ == "__main__":
    unittest.main()
