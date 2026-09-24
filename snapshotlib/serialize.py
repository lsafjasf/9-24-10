"""Deterministic canonical serialization.

Guarantees (see tests/test_serialize.py for counter-example tests):

* dict key order      -- keys are sorted by their canonical form, so insertion
                         order never affects the output bytes.
* float format        -- floats are emitted with repr() (shortest round-trip,
                         stable across CPython versions >= 3.1). -0.0 is
                         normalized to 0.0; NaN/Inf become explicit tagged
                         values instead of platform-dependent literals.
* newlines            -- the canonical form is a single line: every newline
                         inside a string is escaped by the JSON encoder, and
                         the file itself is written in binary mode, so the
                         platform's os.linesep can never leak in.
* set iteration order -- set/frozenset members are sorted by their canonical
                         JSON encoding, so hash randomization (PYTHONHASHSEED)
                         cannot change the output.
"""
from __future__ import annotations

import json
import math

SET_TAG = "~set"
TUPLE_TAG = "~tuple"
BYTES_TAG = "~bytes"
DICT_TAG = "~dict"
FLOAT_TAG = "~float"

_TAGS = {SET_TAG, TUPLE_TAG, BYTES_TAG, DICT_TAG, FLOAT_TAG}


def _normalize_float(value: float):
    if math.isnan(value):
        return {FLOAT_TAG: "nan"}
    if math.isinf(value):
        return {FLOAT_TAG: "inf" if value > 0 else "-inf"}
    # Normalize -0.0 -> 0.0 so the sign of zero cannot cause a spurious diff.
    return value + 0.0


def _normalize_key(key):
    if isinstance(key, str):
        return key
    if isinstance(key, (int, float, bool)) or key is None:
        return normalize(key)
    raise TypeError(f"unsupported dict key type: {type(key).__name__}")


def normalize(value):
    """Convert *value* into a JSON-compatible structure with canonical order."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return _normalize_float(value)
    if isinstance(value, dict):
        items = [(_normalize_key(k), normalize(v)) for k, v in value.items()]
        if all(isinstance(k, str) for k, _ in items):
            # json.dumps(sort_keys=True) orders these; sort anyway so the
            # normalized structure itself is already canonical.
            return {k: v for k, v in sorted(items, key=lambda kv: kv[0])}
        # Non-string keys: encode as an ordered list of [key, value] pairs.
        items.sort(key=lambda kv: canonical_json(kv[0]))
        return {DICT_TAG: [[k, v] for k, v in items]}
    if isinstance(value, list):
        return [normalize(v) for v in value]
    if isinstance(value, tuple):
        return {TUPLE_TAG: [normalize(v) for v in value]}
    if isinstance(value, (set, frozenset)):
        members = [normalize(v) for v in value]
        members.sort(key=canonical_json)
        return {SET_TAG: members}
    if isinstance(value, (bytes, bytearray)):
        return {BYTES_TAG: bytes(value).hex()}
    hook = getattr(value, "__snapshot__", None)
    if callable(hook):
        return normalize(hook())
    raise TypeError(
        f"object of type {type(value).__name__} is not snapshot-serializable; "
        "define __snapshot__() on it"
    )


def canonical_json(normalized) -> str:
    """Serialize an already-normalized structure to canonical JSON text."""
    return json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def canonical_str(value) -> str:
    """Canonical single-line JSON text for any supported value."""
    return canonical_json(normalize(value))


def canonical_bytes(value) -> bytes:
    return (canonical_str(value) + "\n").encode("utf-8")
