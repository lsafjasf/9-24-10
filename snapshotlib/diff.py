"""Path-precise structural diff over normalized snapshot structures."""
from __future__ import annotations

import hashlib
import re

from .serialize import (
    DICT_TAG,
    SET_TAG,
    TUPLE_TAG,
    canonical_json,
)

TRUNCATE_AT = 80

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*$")


def preview(value, limit: int = TRUNCATE_AT) -> str:
    """One-line preview; long values are truncated but keep locating info."""
    text = canonical_json(value)
    if len(text) <= limit:
        return text
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    return f"{text[:limit]}... <truncated: {len(text)} chars total, sha256:{digest}>"


def _is_tagged(value, tag) -> bool:
    return isinstance(value, dict) and set(value.keys()) == {tag}


def _child(path: str, key: str) -> str:
    if _IDENT.match(key):
        return f"{path}.{key}"
    return f"{path}[{canonical_json(key)}]"


def _diff_set(old, new, path, out):
    old_map = {canonical_json(m): m for m in old[SET_TAG]}
    new_map = {canonical_json(m): m for m in new[SET_TAG]}
    for key in sorted(old_map.keys() - new_map.keys()):
        out.append({
            "path": f"{path}{{{preview(old_map[key], 40)}}}",
            "op": "removed",
            "old": preview(old_map[key]),
        })
    for key in sorted(new_map.keys() - old_map.keys()):
        out.append({
            "path": f"{path}{{{preview(new_map[key], 40)}}}",
            "op": "added",
            "new": preview(new_map[key]),
        })


def _diff_list(old, new, path, out):
    common = min(len(old), len(new))
    for i in range(common):
        _diff(old[i], new[i], f"{path}[{i}]", out)
    for i in range(common, len(old)):
        out.append({"path": f"{path}[{i}]", "op": "removed", "old": preview(old[i])})
    for i in range(common, len(new)):
        out.append({"path": f"{path}[{i}]", "op": "added", "new": preview(new[i])})


def _diff_dict(old, new, path, out):
    for key in sorted(old.keys() - new.keys()):
        out.append({"path": _child(path, key), "op": "removed", "old": preview(old[key])})
    for key in sorted(new.keys() - old.keys()):
        out.append({"path": _child(path, key), "op": "added", "new": preview(new[key])})
    for key in sorted(old.keys() & new.keys()):
        _diff(old[key], new[key], _child(path, key), out)


def _tag_of(value):
    if isinstance(value, dict) and len(value) == 1:
        only = next(iter(value))
        if only in (SET_TAG, TUPLE_TAG, DICT_TAG):
            return only
    return type(value).__name__


def _diff(old, new, path, out):
    if _is_tagged(old, SET_TAG) and _is_tagged(new, SET_TAG):
        _diff_set(old, new, path, out)
        return
    if _is_tagged(old, TUPLE_TAG) and _is_tagged(new, TUPLE_TAG):
        _diff_list(old[TUPLE_TAG], new[TUPLE_TAG], path, out)
        return
    if _is_tagged(old, DICT_TAG) and _is_tagged(new, DICT_TAG):
        _diff_list(old[DICT_TAG], new[DICT_TAG], path, out)
        return
    if isinstance(old, dict) and isinstance(new, dict):
        _diff_dict(old, new, path, out)
        return
    if isinstance(old, list) and isinstance(new, list):
        _diff_list(old, new, path, out)
        return
    if _tag_of(old) != _tag_of(new):
        out.append({
            "path": path,
            "op": "type_changed",
            "old": preview(old),
            "new": preview(new),
        })
        return
    if old != new:
        out.append({"path": path, "op": "changed", "old": preview(old), "new": preview(new)})


def diff(old_normalized, new_normalized) -> list:
    """Return a list of diff entries: {path, op, old?, new?}."""
    out = []
    _diff(old_normalized, new_normalized, "$", out)
    return out


def format_report(entries, header: str = "snapshot mismatch") -> str:
    lines = [header, f"{len(entries)} difference(s):"]
    for entry in entries:
        op = entry["op"]
        path = entry["path"]
        if op == "changed":
            lines.append(f"  ~ {path}")
            lines.append(f"      old: {entry['old']}")
            lines.append(f"      new: {entry['new']}")
        elif op == "added":
            lines.append(f"  + {path}")
            lines.append(f"      new: {entry['new']}")
        elif op == "removed":
            lines.append(f"  - {path}")
            lines.append(f"      old: {entry['old']}")
        else:  # type_changed
            lines.append(f"  ! {path} (type changed)")
            lines.append(f"      old: {entry['old']}")
            lines.append(f"      new: {entry['new']}")
    return "\n".join(lines)
