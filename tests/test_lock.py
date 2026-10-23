#!/usr/bin/env python
#
# This is free and unencumbered software released into the public domain.
# See the UNLICENSE file for details.
#
# ------------------------------------------------------------------------
# test_lock.py
# ------------------------------------------------------------------------

import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from monoqueue import Monoqueue
from monoqueue import time as mqtime
from monoqueue.lock import lock, write_json

# Holds the lock in another process until killed.
_HOLDER = """
import sys, time
from pathlib import Path
from monoqueue.lock import lock
with lock(Path(sys.argv[1])):
    print("locked", flush=True)
    time.sleep(60)
"""


class TestLock(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def _hold(self, path):
        holder = subprocess.Popen(
            [sys.executable, "-c", _HOLDER, str(path)],
            stdout=subprocess.PIPE, text=True,
        )
        self.addCleanup(holder.wait)
        self.addCleanup(holder.kill)
        self.assertEqual("locked", holder.stdout.readline().strip())
        return holder

    def test_timeout_while_held(self):
        path = self.dir / "up.lock"
        self._hold(path)
        start = time.monotonic()
        with self.assertRaises(TimeoutError):
            with lock(path, timeout=1):
                self.fail("Acquired a lock held by another process")
        self.assertGreaterEqual(time.monotonic() - start, 1)

    def test_released_when_holder_dies(self):
        path = self.dir / "up.lock"
        holder = self._hold(path)
        holder.kill()  # Even kill -9 releases the lock: no stale locks.
        holder.wait()
        with lock(path, timeout=5):
            pass

    def test_reentry_after_release(self):
        path = self.dir / "up.lock"
        with lock(path, timeout=0):
            pass
        with lock(path, timeout=0):
            pass

    def test_write_json_atomic(self):
        path = self.dir / "items.json"
        write_json({"a": 1}, path)
        write_json({"a": 2}, path)
        self.assertEqual({"a": 2}, json.loads(path.read_text()))
        self.assertEqual(["items.json"], [p.name for p in self.dir.iterdir()])


class TestMetadataMerge(unittest.TestCase):

    def test_concurrent_sessions_keep_both_deferrals(self):
        with tempfile.TemporaryDirectory() as d:
            items_path = Path(d) / "items.json"
            metadata_path = Path(d) / "metadata.json"
            write_json({}, items_path)
            write_json({}, metadata_path)

            # Two UI sessions, loaded at the same time.
            one = Monoqueue({"rules": {}})
            two = Monoqueue({"rules": {}})
            one.load(items_path, metadata_path)
            two.load(items_path, metadata_path)

            later = mqtime.days_later(3)
            one.defer("https://example.com/a", later)
            one.save(items_path=None, metadata_path=metadata_path)
            two.defer("https://example.com/b", later)
            two.save(items_path=None, metadata_path=metadata_path)

            saved = json.loads(metadata_path.read_text())
            self.assertEqual({"https://example.com/a", "https://example.com/b"}, set(saved))
            # Session two now also sees session one's deferral.
            self.assertIn("deferred_until", two.metadata("https://example.com/a"))


if __name__ == '__main__':
    unittest.main()
