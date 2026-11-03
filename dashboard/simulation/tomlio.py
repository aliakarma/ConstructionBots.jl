"""Small TOML reader/writer shared with the Julia worker (TOML is a Julia standard library).

Writes are atomic (temporary file + rename) and both reads and renames are retried,
because on Windows a file that another process has open cannot be replaced.
"""
from __future__ import annotations

import math
import os
import time
import tomllib
from datetime import date, datetime
from pathlib import Path
from typing import Any


def _retry(fn, attempts: int = 40, delay: float = 0.05):
    for i in range(attempts):
        try:
            return fn()
        except (PermissionError, OSError):
            if i == attempts - 1:
                raise
            time.sleep(delay)


def read_toml(path: Path) -> dict[str, Any] | None:
    """Parse a TOML file; None if it does not exist. Retries partial/locked reads briefly."""
    path = Path(path)
    if not path.exists():
        return None

    def load():
        with open(path, "rb") as f:
            return tomllib.load(f)

    for i in range(10):
        try:
            return _retry(load)
        except tomllib.TOMLDecodeError:
            if i == 9:
                raise
            time.sleep(0.05)
    return None


def _key(k: str) -> str:
    if k and all(c.isalnum() or c in "_-" for c in k):
        return k
    return _string(k)


def _string(s: str) -> str:
    out = ['"']
    for c in s:
        if c == '"':
            out.append('\\"')
        elif c == "\\":
            out.append("\\\\")
        elif c == "\n":
            out.append("\\n")
        elif c == "\r":
            out.append("\\r")
        elif c == "\t":
            out.append("\\t")
        elif ord(c) < 0x20 or ord(c) == 0x7F:
            out.append(f"\\u{ord(c):04x}")
        else:
            out.append(c)
    out.append('"')
    return "".join(out)


def _value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if math.isnan(v):
            return "nan"
        if math.isinf(v):
            return "inf" if v > 0 else "-inf"
        return repr(v)
    if isinstance(v, str):
        return _string(v)
    if isinstance(v, (datetime, date)):
        return _string(v.isoformat())
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_value(x) for x in v) + "]"
    raise TypeError(f"cannot write {type(v).__name__} to TOML")


def _is_table_array(v: Any) -> bool:
    return isinstance(v, (list, tuple)) and bool(v) and all(isinstance(x, dict) for x in v)


def dumps(d: dict[str, Any]) -> str:
    """Serialize scalars, lists of scalars, nested tables and arrays of tables. None values are omitted."""
    lines: list[str] = []

    def emit(table: dict[str, Any], prefix: str, header: str | None = None) -> None:
        scalars = {k: v for k, v in table.items()
                   if v is not None and not isinstance(v, dict) and not _is_table_array(v)}
        tables = {k: v for k, v in table.items() if isinstance(v, dict)}
        arrays = {k: v for k, v in table.items() if _is_table_array(v)}
        if header is not None:
            lines.append(header)
        elif prefix and (scalars or not (tables or arrays)):
            lines.append(f"\n[{prefix}]")
        for k in sorted(scalars):
            lines.append(f"{_key(k)} = {_value(scalars[k])}")
        for k in sorted(tables):
            emit(tables[k], f"{prefix}.{_key(k)}" if prefix else _key(k))
        for k in sorted(arrays):
            name = f"{prefix}.{_key(k)}" if prefix else _key(k)
            for item in arrays[k]:
                emit(item, name, header=f"\n[[{name}]]")

    emit(d, "")
    return "\n".join(lines).lstrip("\n") + "\n"


def write_toml_atomic(path: Path, d: dict[str, Any]) -> Path:
    path = Path(path)
    tmp = path.with_name(f"{path.name}.tmp{os.getpid()}")
    tmp.write_text(dumps(d), encoding="utf-8")
    _retry(lambda: os.replace(tmp, path))
    return path
