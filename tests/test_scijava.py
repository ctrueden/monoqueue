#!/usr/bin/env python
#
# This is free and unencumbered software released into the public domain.
# See the UNLICENSE file for details.
#
# ------------------------------------------------------------------------
# test_scijava.py
# ------------------------------------------------------------------------

import unittest
from unittest import mock

from monoqueue import Monoqueue, scijava, time

PR = "https://github.com/scifio/scifio/pull/523"
ISSUE = "https://github.com/scifio/scifio/issues/1"
OTHER_ISSUE = "https://github.com/scifio/scifio/issues/2"
REPO = "https://github.com/scifio/scifio-bf-compat"

ROW = {
    "dev_id": "ctrueden",
    "popups": {
        "components": [{"ga": "io.scif:scifio", "url": "https://github.com/scifio/scifio"}],
        "reviewer_prs": [{"number": 523, "repo": "scifio/scifio", "title": "Fix bug", "url": PR}],
        "support_issues": [
            {"number": 1, "repo": "scifio/scifio", "title": "Use plugins", "url": ISSUE},
            {"number": 2, "repo": "scifio/scifio", "title": "Other", "url": OTHER_ISSUE},
        ],
        "developer_features": [{"number": 1, "repo": "scifio/scifio", "title": "Use plugins", "url": ISSUE}],
        "maintainer_releases": [
            {"ga": "io.scif:scifio-bf-compat", "url": REPO},
            {"ga": "io.scif:scifio-bf-compat-tests", "url": REPO},
        ],
    },
}


def _team(generated):
    return {"generated": generated, "rows": [ROW, {"dev_id": "someone-else", "popups": {}}]}


def _update(mq, team, **config):
    response = mock.Mock()
    response.json.return_value = team
    with mock.patch("monoqueue.scijava.requests.get", return_value=response):
        scijava.update(mq, {"dev_id": "ctrueden", **config})


class TestSciJava(unittest.TestCase):

    def test_collect_merges_roles_per_url(self):
        items = scijava.collect(ROW)
        self.assertEqual(["support_issues", "developer_features"], items[ISSUE]["roles"])
        self.assertEqual("Use plugins", items[ISSUE]["title"])
        self.assertNotIn("https://github.com/scifio/scifio", items)

    def test_collect_release_title(self):
        info = scijava.collect(ROW)[REPO]
        self.assertEqual(["maintainer_releases"], info["roles"])
        self.assertEqual(
            "Release 2 components: io.scif:scifio-bf-compat, io.scif:scifio-bf-compat-tests",
            info["title"],
        )

    def test_default_include_does_not_flood(self):
        mq = Monoqueue({"rules": {}})
        mq.put(ISSUE, {"title": "Use plugins", "issue": {}})
        _update(mq, _team(time.string(time.now())))

        self.assertEqual({PR, ISSUE, REPO}, set(mq.items))
        # Existing items get annotated with their roles, even if not included.
        self.assertEqual(["support_issues", "developer_features"], mq.item(ISSUE)["scijava"]["roles"])

    def test_include_config(self):
        mq = Monoqueue({"rules": {}})
        _update(mq, _team(time.string(time.now())), include="support_issues")
        self.assertEqual({ISSUE, OTHER_ISSUE}, set(mq.items))

    def test_stale_data_becomes_item(self):
        mq = Monoqueue({"rules": {}})
        _update(mq, _team("2026-09-17 09:44 UTC"))
        stale = mq.item(scijava.STATUS_WORKFLOW_URL)
        self.assertIsNotNone(stale)
        self.assertIn("stale", stale["title"])
        self.assertEqual(["stale_status"], stale["scijava"]["roles"])

    def test_fresh_data_no_stale_item(self):
        mq = Monoqueue({"rules": {}})
        _update(mq, _team(time.string(time.now())))
        self.assertIsNone(mq.item(scijava.STATUS_WORKFLOW_URL))


if __name__ == '__main__':
    unittest.main()
