#!/usr/bin/env python
#
# This is free and unencumbered software released into the public domain.
# See the UNLICENSE file for details.
#
# ------------------------------------------------------------------------
# test_tabs.py
# ------------------------------------------------------------------------

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import lz4.block

from monoqueue import Monoqueue, firefox

ISSUE = "https://github.com/scijava/pombast/issues/7"
POST = "https://forum.image.sc/t/biaflows-online-token-error/76067/4"


def _write_profile(root):
    profile = root / "abc.default-release"
    profile.mkdir(parents=True)
    (profile / "prefs.js").write_text("")

    session = {"windows": [{"tabs": [
        {"entries": [{"url": "https://worf.local/mail/", "title": "Mail"}],
         "index": 1, "pinned": True, "lastAccessed": 1792727455580},
        {"entries": [{"url": "https://example.com/old", "title": "Old"},
                     {"url": ISSUE + "#issuecomment-1", "title": "Tab title"}],
         "index": 2, "lastAccessed": 1792727455580},
        {"entries": [{"url": "about:newtab"}], "index": 1},
    ]}], "cookies": [{"name": "secret"}]}
    data = json.dumps(session).encode()
    (profile / "sessionstore.jsonlz4").write_bytes(b"mozLz40\0" + lz4.block.compress(data))

    cx = sqlite3.connect(profile / "synced-tabs.db")
    cx.execute("create table tabs (guid text, record text, last_modified integer)")
    for guid, name, modified, tabs in [
        ("a", "curtis’s Firefox on odo", 1792725687000,
         [{"title": "Biaflows", "urlHistory": [POST], "lastUsed": 1792725687}]),
        ("b", "Firefox on samsung SM-S908U", 1792700000000, []),
    ]:
        cx.execute("insert into tabs values (?, ?, ?)",
                   (guid, json.dumps({"clientName": name, "tabs": tabs}), modified))
    cx.commit()
    cx.close()


class TestTabs(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _write_profile(self.root / "firefox")
        patches = [
            mock.patch.object(firefox, "_PROFILE_PARENTS", [str(self.root / "firefox")]),
            mock.patch("monoqueue.firefox.socket.gethostname", return_value="laforge.local"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        self._tmp.cleanup()

    def test_snapshot(self):
        snap = firefox.snapshot()
        self.assertEqual("laforge", snap["host"])
        devices = snap["devices"]
        self.assertEqual({"laforge", "odo", "samsung SM-S908U"}, set(devices))

        # Current entry of each unpinned http(s) tab; nothing else leaks.
        local = devices["laforge"]["tabs"]
        self.assertEqual([ISSUE + "#issuecomment-1"], [t["url"] for t in local])
        self.assertEqual({"url", "title", "last_accessed"}, set(local[0]))
        self.assertNotIn("secret", json.dumps(snap))

        self.assertEqual([POST], [t["url"] for t in devices["odo"]["tabs"]])
        self.assertEqual("2026-10-23T03:21:27Z", devices["odo"]["seen"])

    def test_snapshot_reads_write_ahead_log(self):
        # While Firefox runs, its latest synced tabs may be only in the WAL.
        db = self.root / "firefox" / "abc.default-release" / "synced-tabs.db"
        cx = sqlite3.connect(db)
        self.addCleanup(cx.close)
        cx.execute("pragma journal_mode=wal")
        cx.execute("pragma wal_autocheckpoint=0")
        record = {"clientName": "Firefox on troi", "tabs": [
            {"title": "Issue", "urlHistory": [ISSUE], "lastUsed": 1792725687}]}
        cx.execute("insert into tabs values (?, ?, ?)", ("c", json.dumps(record), 1792725687000))
        cx.commit()
        self.assertTrue(db.with_name(db.name + "-wal").exists())

        devices = firefox.snapshot()["devices"]
        self.assertEqual([ISSUE], [t["url"] for t in devices["troi"]["tabs"]])

    def test_update_tabs(self):
        db = self.root / "firefox" / "abc.default-release" / "synced-tabs.db"
        cx = sqlite3.connect(db)
        record = {"clientName": "Firefox on troi", "tabs": [
            {"title": "From troi", "urlHistory": [ISSUE], "lastUsed": 1792725687}]}
        cx.execute("insert into tabs values (?, ?, ?)", ("c", json.dumps(record), 1792725687000))
        cx.commit()
        cx.close()

        mq = Monoqueue({"rules": {}})
        mq.put(ISSUE, {"title": "GitHub title", "issue": {}})
        firefox.update_tabs(mq, {
            "exclude": "\n^https://forum\\.image\\.sc/\n",
            # NB: Keep the fixed timestamps from aging out in the future.
            "max_device_age_days": "100000",
        })

        # The forum post is excluded; the issue merges tabs from two devices.
        self.assertEqual([ISSUE], list(mq.items))
        item = mq.item(ISSUE)
        self.assertEqual("GitHub title", item["title"])
        self.assertEqual({"laforge", "troi"}, {t["device"] for t in item["tabs"]})

        mq._score()
        self.assertIn("seconds_since_tab_access", item)

    def test_update_tabs_skips_dormant_devices(self):
        mq = Monoqueue({"rules": {}})
        firefox.update_tabs(mq, {"max_device_age_days": "0"})
        self.assertEqual({}, mq.items)


if __name__ == '__main__':
    unittest.main()
