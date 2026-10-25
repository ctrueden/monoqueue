#!/usr/bin/env python
#
# This is free and unencumbered software released into the public domain.
# See the UNLICENSE file for details.
#
# ------------------------------------------------------------------------
# test_notifications.py
# ------------------------------------------------------------------------

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from monoqueue import Monoqueue, notifications, time


def _notification(reason, kind, api_url, title="Something"):
    return {
        "id": "1",
        "reason": reason,
        "unread": True,
        "updated_at": "2026-10-23T12:00:00Z",
        "subject": {"title": title, "type": kind, "url": api_url},
        "repository": {"full_name": "scijava/pombast", "html_url": "https://github.com/scijava/pombast"},
    }


NOTIFICATIONS = [
    _notification("review_requested", "PullRequest",
                  "https://api.github.com/repos/scijava/pombast/pulls/12", "Fix drift"),
    _notification("mention", "Issue",
                  "https://api.github.com/repos/scijava/pombast/issues/7", "Timezones"),
    _notification("subscribed", "Issue",
                  "https://api.github.com/repos/scijava/pombast/issues/8", "Just watching"),
    _notification("assign", "Release",
                  "https://api.github.com/repos/scijava/pombast/releases/1", "v1.0"),
]


class TestNotifications(unittest.TestCase):

    def setUp(self):
        # By default, every issue and PR is open, with nobody requested.
        patch = mock.patch.object(notifications, "subjects", return_value=("me", {}))
        self.subjects = patch.start()
        self.addCleanup(patch.stop)

    def test_html_url(self):
        urls = [notifications.html_url(n) for n in NOTIFICATIONS]
        self.assertEqual([
            "https://github.com/scijava/pombast/pull/12",
            "https://github.com/scijava/pombast/issues/7",
            "https://github.com/scijava/pombast/issues/8",
            "https://github.com/scijava/pombast/releases",
        ], urls)

    def test_html_url_without_subject_url(self):
        n = _notification("mention", "Discussion", None)
        self.assertEqual("https://github.com/scijava/pombast", notifications.html_url(n))

    def test_update_keeps_personal_reasons(self):
        mq = Monoqueue({"rules": {}})
        with mock.patch.object(notifications, "fetch", return_value=NOTIFICATIONS):
            notifications.update(mq, {"token": "x"})
        self.assertEqual({
            "https://github.com/scijava/pombast/pull/12",
            "https://github.com/scijava/pombast/issues/7",
            "https://github.com/scijava/pombast/releases",
        }, set(mq.items))
        pr = mq.item("https://github.com/scijava/pombast/pull/12")
        self.assertEqual("Fix drift", pr["title"])
        self.assertEqual("review_requested", pr["notification"]["reason"])

    def test_update_reasons_config(self):
        mq = Monoqueue({"rules": {}})
        with mock.patch.object(notifications, "fetch", return_value=NOTIFICATIONS):
            notifications.update(mq, {"token": "x", "reasons": "subscribed"})
        self.assertEqual({"https://github.com/scijava/pombast/issues/8"}, set(mq.items))

    def test_update_drops_moot_notifications(self):
        pr = "https://github.com/scijava/pombast/pull/12"
        issue = "https://github.com/scijava/pombast/issues/7"
        for state, reviewers, kept in [
            ("open", ["me", "alice", "bob"], True),
            ("open", ["org/team"], True),     # Requested of a team.
            ("open", ["alice"], False),       # No longer requested of me.
            ("closed", ["me"], False),
            ("merged", ["me"], False),
        ]:
            self.subjects.return_value = ("me", {
                pr: {"state": state, "assignees": [], "reviewers": reviewers},
                issue: {"state": "closed", "assignees": [], "reviewers": []},
            })
            mq = Monoqueue({"rules": {}})
            with mock.patch.object(notifications, "fetch", return_value=NOTIFICATIONS):
                notifications.update(mq, {"token": "x"})
            self.assertEqual(kept, pr in mq.items, (state, reviewers))
            # Mentions are kept even when closed, with the state.
            self.assertEqual("closed", mq.item(issue)["notification"]["state"])
            if kept and state == "open" and "me" in reviewers:
                self.assertEqual(2, mq.item(pr)["notification"]["others_requested"])

    def test_fetch_follows_pages(self):
        pages = [
            mock.Mock(links={"next": {"url": "https://api.github.com/notifications?page=2"}},
                      json=lambda: NOTIFICATIONS[:2]),
            mock.Mock(links={}, json=lambda: NOTIFICATIONS[2:]),
        ]
        with mock.patch("requests.Session.get", side_effect=pages) as get:
            self.assertEqual(NOTIFICATIONS, notifications.fetch("x"))
        self.assertEqual(2, get.call_count)


class TestSubjects(unittest.TestCase):

    def test_subjects(self):
        pr = "https://github.com/scijava/pombast/pull/12"
        response = mock.Mock(json=lambda: {"data": {
            "viewer": {"login": "me"},
            "s0": {"state": "OPEN", "assignees": {"nodes": [{"login": "me"}]},
                   "reviewRequests": {"nodes": [
                       {"requestedReviewer": {"login": "alice"}},
                       {"requestedReviewer": {"combinedSlug": "org/team"}},
                       {"requestedReviewer": {}},  # E.g. a bot.
                   ]}},
        }})
        with mock.patch("requests.post", return_value=response) as post:
            me, states = notifications.subjects("x", [pr, "https://github.com/o/r/releases"])
        self.assertEqual("me", me)
        self.assertEqual({pr: {"state": "open", "assignees": ["me"], "reviewers": ["alice", "org/team"]}}, states)
        self.assertIn(f'resource(url: "{pr}")', post.call_args[1]["json"]["query"])
        self.assertNotIn("releases", post.call_args[1]["json"]["query"])


class TestStatus(unittest.TestCase):

    def test_summary_and_status_file(self):
        mq = Monoqueue({"rules": {}})
        soon = time.string(time.days_later(0.5))
        mq.put("https://example.com/due-soon", {"title": "Soon", "due": soon})
        mq.put("https://example.com/later", {"title": "Later", "due": time.string(time.days_later(5))})
        mq.put("monoqueue:source/x", {"title": "Fix monoqueue source: x", "alert": True})
        mq.put("https://example.com/deferred", {
            "title": "Deferred", "due": soon,
            "created": "2026-01-01T00:00:00Z", "updated": "2026-01-01T00:00:00Z",
        })
        mq.defer("https://example.com/deferred", time.days_later(2))
        mq._score()

        self.assertEqual({"alerts": 1, "due": 1, "active": 3}, mq.summary())
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "status"
            mq.save_status(path)
            alerts, due, active, written = path.read_text().split()
            self.assertEqual(("1", "1", "3"), (alerts, due, active))
            self.assertLess(abs(int(written) - time.now().timestamp()), 60)


if __name__ == '__main__':
    unittest.main()
