#!/usr/bin/env python
#
# This is free and unencumbered software released into the public domain.
# See the UNLICENSE file for details.
#
# ------------------------------------------------------------------------
# test_monoqueue.py
# ------------------------------------------------------------------------

import datetime
import json
import tempfile
import unittest
from pathlib import Path

from monoqueue import Monoqueue, time


def _mq(**sections):
    return Monoqueue({"rules": {}, **sections})


class TestMonoqueue(unittest.TestCase):

    def test_put_normalizes_and_merges(self):
        mq = _mq()
        a = mq.put("https://github.com/o/r/issues/1#issuecomment-9", {
            "title": "From a tab",
            "created": "2026-10-01T00:00:00Z",
            "updated": "2026-10-20T00:00:00Z",
            "tab": {"device": "odo"},
        })
        b = mq.put("https://github.com/o/r/issues/1", {
            "title": "From GitHub",
            "created": "2026-09-01T00:00:00.000Z",
            "updated": "2026-10-10T00:00:00Z",
            "issue": {"number": 1},
        })
        self.assertEqual(a, b)
        self.assertEqual(1, len(mq.items))
        item = mq.item(a)
        self.assertEqual("From GitHub", item["title"])
        self.assertEqual("2026-09-01T00:00:00.000Z", item["created"])
        self.assertEqual("2026-10-20T00:00:00Z", item["updated"])
        self.assertIn("tab", item)
        self.assertIn("issue", item)

    def test_configured_discourse_host(self):
        mq = _mq(**{"forum.example.com": {"handler": "discourse"}})
        self.assertEqual(
            "https://forum.example.com/t/5",
            mq.normalize("https://forum.example.com/t/topic/5/1"),
        )

    def test_load_normalizes_metadata_keys(self):
        with tempfile.TemporaryDirectory() as d:
            items_path = Path(d) / "items.json"
            metadata_path = Path(d) / "metadata.json"
            items_path.write_text("{}")
            metadata_path.write_text(json.dumps({
                "https://forum.image.sc/t/old-slug/7": {"deferred_until": "x"},
            }))
            mq = _mq()
            mq.load(items_path, metadata_path)
            self.assertEqual(
                {"deferred_until": "x"},
                mq.metadata("https://forum.image.sc/t/7"),
            )

    def test_deferred_item_wakes_on_update(self):
        mq = _mq()
        url = mq.put("https://example.com/a", {
            "title": "A",
            "created": "2026-01-01T00:00:00Z",
            "updated": "2026-01-01T00:00:00Z",
        })
        mq.defer(url, time.days_later(7))
        self.assertFalse(mq.active(url))

        # Someone replies after the deferral: the item becomes active again.
        later = time.now() + datetime.timedelta(minutes=5)
        mq.put(url, {"updated": time.string(later)})
        self.assertTrue(mq.active(url))


if __name__ == '__main__':
    unittest.main()
