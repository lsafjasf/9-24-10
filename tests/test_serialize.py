"""Determinism tests, including counter-examples showing what *would* go
wrong with a naive serializer (and therefore must not happen with ours)."""
import json
import math
import subprocess
import sys
import unittest

from snapshotlib import canonical_bytes, canonical_str, normalize


class DictOrderTests(unittest.TestCase):
    def test_insertion_order_is_irrelevant(self):
        a = {"x": 1, "y": 2, "z": {"b": 1, "a": 2}}
        b = {"z": {"a": 2, "b": 1}, "y": 2, "x": 1}
        self.assertEqual(canonical_bytes(a), canonical_bytes(b))

    def test_counter_example_naive_json_depends_on_insertion_order(self):
        # This is the meaningless diff we must NOT produce: plain json.dumps
        # keeps insertion order, so equal dicts serialize differently.
        a = {"x": 1, "y": 2}
        b = {"y": 2, "x": 1}
        self.assertNotEqual(json.dumps(a), json.dumps(b))  # naive: differs
        self.assertEqual(canonical_str(a), canonical_str(b))  # ours: identical


class FloatTests(unittest.TestCase):
    def test_float_format_is_shortest_roundtrip(self):
        text = canonical_str({"v": 0.1})
        self.assertIn("0.1", text)
        self.assertNotIn("0.10000000000000001", text)

    def test_negative_zero_normalized(self):
        self.assertEqual(canonical_bytes(-0.0), canonical_bytes(0.0))

    def test_counter_example_negative_zero_differs_in_naive_json(self):
        self.assertNotEqual(json.dumps(-0.0), json.dumps(0.0))  # "-0.0" vs "0.0"
        self.assertEqual(canonical_str(-0.0), canonical_str(0.0))

    def test_non_finite_floats_are_deterministic(self):
        self.assertEqual(canonical_bytes(math.nan), canonical_bytes(math.nan))
        self.assertEqual(canonical_bytes(math.inf), canonical_bytes(math.inf))
        self.assertEqual(canonical_bytes(-math.inf), canonical_bytes(-math.inf))

    def test_extreme_floats_stable(self):
        for value in (5e-324, 1.7976931348623157e308, 2**0.5, 1 / 3):
            self.assertEqual(canonical_bytes(value), canonical_bytes(value))
            self.assertIn(repr(value).replace("inf", "inf"), canonical_str(value))


class SetOrderTests(unittest.TestCase):
    def test_set_insertion_order_is_irrelevant(self):
        a = {"apple", "banana", "cherry", "date"}
        b = set(reversed(["apple", "banana", "cherry", "date"]))
        self.assertEqual(canonical_bytes(a), canonical_bytes(b))

    def test_set_members_sorted_canonically(self):
        text = canonical_str({"s": {"b", "a", "c"}})
        self.assertLess(text.index('"a"'), text.index('"b"'))
        self.assertLess(text.index('"b"'), text.index('"c"'))

    def test_set_output_stable_across_hash_seeds(self):
        # PYTHONHASHSEED changes str hash randomization, hence set iteration
        # order. Our canonical form must be identical across seeds.
        code = (
            "import sys; sys.path.insert(0, '.');"
            "from snapshotlib import canonical_str;"
            "print(canonical_str({'s': {'alpha','beta','gamma','delta','eps'}}))"
        )
        outputs = set()
        for seed in ("0", "1", "42"):
            result = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True, text=True, check=True,
                env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"},
                cwd=_repo_root(),
            )
            outputs.add(result.stdout)
        self.assertEqual(len(outputs), 1, f"hash seed leaked into output: {outputs}")

    def test_counter_example_naive_set_dump_varies_with_hash_seed(self):
        # Demonstrates the noise source: list(set) order is not canonical.
        code = "print(list({'alpha','beta','gamma','delta','eps'}))"
        outputs = set()
        for seed in ("0", "1", "42", "7", "99"):
            result = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True, text=True, check=True,
                env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"},
            )
            outputs.add(result.stdout)
        self.assertGreater(len(outputs), 1, "expected naive set order to vary")


class NewlineTests(unittest.TestCase):
    def test_embedded_newlines_are_escaped(self):
        raw = canonical_bytes({"text": "line1\nline2\r\nline3"})
        # Exactly one raw newline: the single record terminator.
        self.assertEqual(raw.count(b"\n"), 1)
        self.assertEqual(raw.count(b"\r"), 0)
        self.assertIn(b"line1\\nline2\\r\\nline3", raw)

    def test_crlf_and_lf_remain_real_differences(self):
        # Normalization must not hide genuine content differences.
        self.assertNotEqual(canonical_bytes("a\nb"), canonical_bytes("a\r\nb"))


class StructureTests(unittest.TestCase):
    def test_tuple_and_list_are_distinguishable(self):
        self.assertNotEqual(canonical_bytes((1, 2)), canonical_bytes([1, 2]))

    def test_nested_mixed_structures(self):
        value = {
            "set": {3, 1, 2},
            "tuple": ("b", {"k": [1.5, None, True]}),
            "bytes": b"\x00\xff",
        }
        first = canonical_bytes(value)
        second = canonical_bytes({
            "bytes": b"\x00\xff",
            "tuple": ("b", {"k": [1.5, None, True]}),
            "set": {2, 3, 1},
        })
        self.assertEqual(first, second)

    def test_non_string_dict_keys_sorted_canonically(self):
        a = {2: "b", 1: "a", 10: "j"}
        b = {10: "j", 2: "b", 1: "a"}
        self.assertEqual(canonical_bytes(a), canonical_bytes(b))
        # Numeric sort, not lexicographic: 2 must come before 10.
        text = canonical_str(a)
        self.assertLess(text.index('"a"'), text.index('"j"'))

    def test_unsupported_type_raises_clear_error(self):
        with self.assertRaises(TypeError):
            normalize(object())


def _repo_root():
    import pathlib

    return str(pathlib.Path(__file__).resolve().parent.parent)


if __name__ == "__main__":
    unittest.main()
