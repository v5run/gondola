"""Portable paths for anything written to JSON (closes, outbox, bucket index).

Stored paths are relative POSIX strings (e.g. "reports/2026-11-05.pdf"), never absolute machine paths, so the
out/ folder can move between machines (Linux container <-> Windows laptop). `resolve` reads both the new
relative form and older absolute paths.
"""
from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath

ROOT = Path(__file__).resolve().parents[1]


def rel(p: str | Path | None, base: str | Path = ROOT) -> str | None:
    """`p` relative to `base` as a POSIX string; just the file name if it lies outside `base`."""
    if p is None:
        return None
    pp = Path(p)
    try:
        return pp.resolve().relative_to(Path(base).resolve()).as_posix()
    except ValueError:
        return pp.name if pp.is_absolute() else PurePosixPath(*PureWindowsPath(str(p)).parts).as_posix()


def resolve(s: str | Path | None, base: str | Path = ROOT, anchor: str | None = None) -> Path | None:
    """Turn a stored path back into a real one. Relative -> under `base`. A stale absolute path from another machine is
    rebased onto `base` after `anchor` (e.g. "out/") if it contains it."""
    if not s:
        return None
    p = Path(s)
    if not p.is_absolute() and not PureWindowsPath(str(s)).is_absolute() and not str(s).startswith("/"):
        return Path(base) / p
    if p.exists():
        return p
    posix = str(s).replace("\\", "/")
    if anchor and anchor in posix:
        return Path(base) / posix.split(anchor, 1)[1]
    return p
