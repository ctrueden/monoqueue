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
from unittest import mock

from monoqueue import HANDLERS, Monoqueue, read_config, time


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
        self.assertEqual("From a tab", item["title"])  # First title wins.
        self.assertEqual("2026-09-01T00:00:00.000Z", item["created"])
        self.assertEqual("2026-10-20T00:00:00Z", item["updated"])
        self.assertIn("tab", item)
        self.assertIn("issue", item)

    def test_score_rounds_computed_values(self):
        mq = Monoqueue({"rules": {
            "rule1": "(10 if n > 10 else n / 3) -> +X: capped",
            "rule2": "n -> +X: raw",
        }})
        mq.put("https://example.com/a", {"n": 4})
        mq.put("https://example.com/b", {"n": 30})
        mq._score()
        a = mq.impact("https://example.com/a")
        self.assertAlmostEqual(1 + 4 / 3 + 4, a.value)
        self.assertEqual(["+1.3: capped", "+4: raw"], a.rules)
        self.assertEqual(41, mq.impact("https://example.com/b").value)

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



class TestReadConfig(unittest.TestCase):

    def test_strips_end_of_line_comments(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "monoqueue.conf"
            path.write_text(
                "[source]\n"
                "verify = false  # TEMP: until the cert is fixed\n"
                "empty = #\n"
                "query = #development tags:imagej status:open\n"
                "link = https://example.com/#/tasks/{uid}\n"
                "rule = a ; b -> +1: x#y\n"
                "pct = 100%%\n"
            )
            config = read_config(path)
        self.assertEqual("false", config["source"]["verify"])
        self.assertEqual("#", config["source"]["empty"])
        self.assertEqual("#development tags:imagej status:open", config["source"]["query"])
        self.assertEqual("https://example.com/#/tasks/{uid}", config["source"]["link"])
        self.assertEqual("a ; b -> +1: x#y", config["source"]["rule"])
        self.assertEqual("100%", config["source"]["pct"])


class TestUpdate(unittest.TestCase):
    """
    Tests for Monoqueue.update, with fake source handlers.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.fail_alpha = False
        handlers = dict(HANDLERS, alpha=self._alpha, beta=self._beta, gamma=self._gamma)
        patch = mock.patch.dict(HANDLERS, handlers)
        patch.start()
        self.addCleanup(patch.stop)

    def _alpha(self, mq, config):
        if self.fail_alpha: raise RuntimeError("401 Bad credentials")
        mq.put("https://example.com/a", {"title": "A"})

    def _beta(self, mq, config):
        mq.put("https://example.com/a#frag", {"title": "B's title for A", "beta": 1})
        mq.put("https://example.com/b", {"title": "B"})

    def _gamma(self, mq, config):
        # Weak items only annotate items that other sources reported.
        mq.put("https://example.com/b", {"gamma": True}, weak=True)
        mq.put("https://example.com/c", {"title": "C", "gamma": True}, weak=True)

    def _mq(self):
        mq = Monoqueue({"rules": {}, "alpha": {}, "beta": {}, "gamma": {}})
        mq.sources_dir = Path(self._tmp.name)
        return mq

    def test_merge(self):
        mq = self._mq()
        mq.update()
        self.assertEqual({"https://example.com/a", "https://example.com/b"}, set(mq.items))
        a = mq.item("https://example.com/a")
        self.assertEqual("A", a["title"])
        self.assertEqual(1, a["beta"])
        self.assertEqual(["alpha", "beta"], a["sources"])
        b = mq.item("https://example.com/b")
        self.assertTrue(b["gamma"])
        self.assertEqual(["beta", "gamma"], b["sources"])
        self.assertNotIn("weak", b)

    def test_failing_source_keeps_last_items(self):
        self._mq().update()

        self.fail_alpha = True
        mq = self._mq()
        mq.update()
        alert_url = "monoqueue:source/alpha"
        self.assertIn("https://example.com/a", mq.items)
        self.assertEqual(["alpha", "beta"], mq.item("https://example.com/a")["sources"])

        alert = mq.item(alert_url)
        self.assertEqual("Fix monoqueue source: alpha", alert["title"])
        self.assertIn("401 Bad credentials", alert["description"])
        self.assertIn("Traceback", alert["description"])
        self.assertEqual(alert_url, mq.urls()[0])

        # Failing again keeps the original failure time.
        since = alert["created"]
        mq.update()
        self.assertEqual(since, mq.item(alert_url)["created"])

        # Once the source works again, the alert goes away.
        self.fail_alpha = False
        mq.update()
        self.assertNotIn(alert_url, mq.items)

    def test_failing_source_without_success(self):
        self.fail_alpha = True
        mq = self._mq()
        mq.update()
        self.assertEqual("B's title for A", mq.item("https://example.com/a")["title"])
        self.assertIn("no items in the queue", mq.item("monoqueue:source/alpha")["description"])

    def test_unknown_handler_is_a_failing_source(self):
        mq = Monoqueue({"rules": {}, "bogus": {}})
        mq.sources_dir = Path(self._tmp.name)
        mq.update()
        self.assertIn("Unsupported source type", mq.item("monoqueue:source/bogus")["description"])

    def test_update_some_sources_merges_all(self):
        self._mq().update()
        self.fail_alpha = True
        mq = self._mq()
        mq.update(["beta"])  # alpha is not fetched, so does not fail.
        self.assertEqual({"https://example.com/a", "https://example.com/b"}, set(mq.items))
        self.assertNotIn("monoqueue:source/alpha", mq.items)


if __name__ == '__main__':
    unittest.main()
