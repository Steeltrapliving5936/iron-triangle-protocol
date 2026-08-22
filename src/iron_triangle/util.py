"""Small shared helpers: time, paths, atomic writes, portable locking."""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import os
import pathlib
import sys
from typing import Any, Iterator


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def expand_path(value: str) -> pathlib.Path:
    return pathlib.Path(os.path.expandvars(os.path.expanduser(value))).resolve()


def atomic_json(path: pathlib.Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def append_jsonl(path: pathlib.Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


@contextlib.contextmanager
def exclusive_lock(path: pathlib.Path, blocking: bool = True) -> Iterator[None]:
    """Best-effort cross-process advisory lock.

    Uses fcntl on POSIX and msvcrt on Windows; when neither is available the
    lock degrades to a no-op. Single-instance semantics for the daemon remain
    best-effort by design and are documented as such.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as handle:
        locked = False
        try:
            if sys.platform == "win32":
                import msvcrt

                mode = msvcrt.LK_NBLCK if not blocking else msvcrt.LK_LOCK
                try:
                    msvcrt.locking(handle.fileno(), mode, 1)
                    locked = True
                except OSError:
                    if blocking:
                        raise
            else:
                import fcntl

                flags = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
                fcntl.flock(handle.fileno(), flags)
                locked = True
        except ImportError:
            locked = False
        try:
            yield
        finally:
            if locked:
                try:
                    if sys.platform == "win32":
                        import msvcrt

                        handle.seek(0)
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except (ImportError, OSError):
                    pass
