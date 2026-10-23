#!/usr/bin/env python
#
# This is free and unencumbered software released into the public domain.
# See the UNLICENSE file for details.
#
# ------------------------------------------------------------------------
# lock.py
# ------------------------------------------------------------------------

"""
Utility functions for safe concurrent access to monoqueue's files.

Locks are advisory OS-level file locks, which the OS releases when the
process holding them exits, however it exits. So unlike lock files
whose mere existence means "locked", they can never go stale.
"""

import contextlib
import json
import os
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Optional

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None
    import msvcrt

_POLL_INTERVAL = 0.5


@contextlib.contextmanager
def lock(path: Path, timeout: Optional[float] = None) -> Iterator[None]:
    """
    Hold an exclusive lock on the given lock file.

    :param path:
        The lock file, which is created if needed.
    :param timeout:
        Seconds to wait for the lock, or None to wait forever.
    :raise TimeoutError:
        If the lock is not acquired within the timeout.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = None if timeout is None else time.monotonic() + timeout
    with open(path, "a+") as f:
        while not _try_lock(f):
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError(f"Timed out waiting for lock: {path}")
            time.sleep(_POLL_INTERVAL)
        try:
            yield
        finally:
            _unlock(f)


def _try_lock(f) -> bool:
    try:
        if fcntl:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        else:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        return True
    except OSError:
        return False


def _unlock(f) -> None:
    if fcntl:
        fcntl.flock(f, fcntl.LOCK_UN)
    else:
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)


def write_json(data: Any, path: Path) -> None:
    """
    Write JSON data to a file atomically: readers see either the old
    file or the new one, never a partially written one.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    finally:
        if tmp.exists(): tmp.unlink()
