import unittest

from snapshotlib import diff, format_report, normalize, preview


def d(old, new):
    return diff(normalize(old), normalize(new))


class PathPrecisionTests(unittest.TestCase):
    def test_nested_dict_and_index_path(self):
        entries = d({"a": [{"b": 1}]}, {"a": [{"b": 2}]})
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["path"], "$.a[0].b")
        self.assertEqual(entries[0]["op"], "changed")

    def test_added_and_removed_keys(self):
        entries = d({"keep": 1, "gone": 2}, {"keep": 1, "fresh": 3})
        by_path = {e["path"]: e for e in entries}
        self.assertEqual(by_path["$.gone"]["op"], "removed")
        self.assertEqual(by_path["$.fresh"]["op"], "added")

    def test_list_growth_paths(self):
        entries = d([1, 2], [1, 2, 3, 4])
        self.assertEqual([e["path"] for e in entries], ["$[2]", "$[3]"])
        self.assertTrue(all(e["op"] == "added" for e in entries))

    def test_type_change(self):
        entries = d({"v": [1]}, {"v": "1"})
        self.assertEqual(entries[0]["op"], "type_changed")
        self.assertEqual(entries[0]["path"], "$.v")

    def test_set_member_paths(self):
        entries = d({"s": {1, 2, 3}}, {"s": {2, 3, 4}})
        by_op = {e["op"]: e for e in entries}
        self.assertEqual(by_op["removed"]["path"], "$.s{1}")
        self.assertEqual(by_op["added"]["path"], "$.s{4}")

    def test_weird_key_quoted(self):
        entries = d({"a b": 1}, {"a b": 2})
        self.assertEqual(entries[0]["path"], '$["a b"]')

    def test_equal_values_produce_no_entries(self):
        self.assertEqual(d({"x": [1, {"y": 2}]}, {"x": [1, {"y": 2}]}), [])


class TruncationTests(unittest.TestCase):
    def test_long_values_truncated_but_locatable(self):
        long_old = "x" * 500
        long_new = "y" * 500
        entries = d({"big": long_old}, {"big": long_new})
        entry = entries[0]
        self.assertEqual(entry["path"], "$.big")
        self.assertIn("truncated", entry["old"])
        self.assertIn("502 chars total", entry["old"])  # 500 chars + 2 quotes
        self.assertIn("sha256:", entry["old"])
        self.assertLess(len(entry["old"]), 160)

    def test_report_format(self):
        report = format_report(d({"a": 1, "b": 2}, {"a": 1, "b": 3, "c": 4}))
        self.assertIn("~ $.b", report)
        self.assertIn("+ $.c", report)
        self.assertIn("old: 2", report)
        self.assertIn("new: 3", report)


if __name__ == "__main__":
    unittest.main()
