#!/usr/bin/env python
#
# This is free and unencumbered software released into the public domain.
# See the UNLICENSE file for details.
#
# ------------------------------------------------------------------------
# test_promote.py
# ------------------------------------------------------------------------

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from monoqueue import Monoqueue, agent, promote

TAB = "https://example.com/an-article"
ISSUE = "https://github.com/ctrueden/tasks/issues/7"


class TestLink(unittest.TestCase):

    def setUp(self):
        self.mq = Monoqueue({"rules": {"rule1": "tabs -> +5: open in a tab"}})
        self.mq.put(TAB, {"title": "An article", "tabs": [{"device": "odo"}], "sources": ["tabs"]})

    def test_link_into_existing_item(self):
        self.mq.put(ISSUE, {"title": "Read the article", "issue": {"number": 7}, "sources": ["github"]})
        self.mq.metadata(TAB)["note"] = "Relevant to worf"
        self.mq._score()

        self.assertEqual(ISSUE, self.mq.link(TAB, ISSUE))
        self.assertEqual([ISSUE], list(self.mq.items))
        item = self.mq.item(ISSUE)
        self.assertEqual("Read the article", item["title"])  # The target's title wins.
        self.assertEqual([{"device": "odo"}], item["tabs"])
        self.assertEqual(["github", "tabs"], item["sources"])
        self.assertEqual([TAB], self.mq.metadata(ISSUE)["links"])
        self.assertEqual("Relevant to worf", self.mq.metadata(ISSUE)["note"])
        self.assertEqual(6, self.mq.impact(ISSUE).value)  # Rescored with the tab.

    def test_link_into_missing_item(self):
        # E.g. a new issue that the GitHub source has not fetched yet.
        self.mq._score()
        self.mq.link(TAB, ISSUE)
        self.assertEqual([ISSUE], list(self.mq.items))
        self.assertEqual("An article", self.mq.item(ISSUE)["title"])
        self.assertEqual(6, self.mq.impact(ISSUE).value)

    def test_links_persist(self):
        with tempfile.TemporaryDirectory() as tmp:
            items, metadata = Path(tmp) / "items.json", Path(tmp) / "metadata.json"
            self.mq.save(items, metadata)
            self.mq.link(TAB, ISSUE)
            self.mq.save(items_path=None, metadata_path=metadata)

            # Sources still report the tab separately, but it is linked in.
            mq = Monoqueue({"rules": {}})
            mq.load(items, metadata)
            self.assertEqual([ISSUE], list(mq.items))

    def test_link_follows_chains(self):
        other = "https://example.com/another"
        self.mq.put(other, {"title": "Another"})
        self.mq._score()
        self.mq.link(other, TAB)
        self.mq.link(TAB, ISSUE)
        self.assertEqual([ISSUE], list(self.mq.items))
        self.assertEqual({TAB, other}, set(self.mq.metadata(ISSUE)["links"]))
        self.assertEqual(ISSUE, self.mq.metadata(other)["linked_to"])

    def test_reload_metadata_sees_other_processes(self):
        with tempfile.TemporaryDirectory() as tmp:
            items, metadata = Path(tmp) / "items.json", Path(tmp) / "metadata.json"
            self.mq.save(items, metadata)
            self.mq.load(items, metadata)
            metadata.write_text(json.dumps({TAB: {"triage": {"size": "S"}}}))
            self.mq.reload_metadata(metadata)
            self.assertEqual("S", self.mq.metadata(TAB)["triage"]["size"])


class TestPromote(unittest.TestCase):

    def test_candidate_repos(self):
        mq = Monoqueue({"rules": {}})
        url = mq.put("https://github.com/scijava/pombast/blob/main/README.md", {
            "title": "README", "description": "See https://github.com/scijava/jgo/issues/1.",
        })
        self.assertEqual(
            ["scijava/pombast", "scijava/jgo", "me/tasks"],
            promote.candidate_repos(mq, url, {"repo": "me/tasks"}),
        )
        self.assertEqual(["me/tasks"], promote.candidate_repos(mq, TAB, {"repo": "me/tasks"}))
        self.assertEqual([], promote.candidate_repos(mq, TAB))

    def test_check_promotable(self):
        mq = Monoqueue({"rules": {}})
        with self.assertRaises(ValueError): promote.check_promotable(mq, ISSUE)
        with self.assertRaises(ValueError): promote.check_promotable(mq, "monoqueue:source/x")
        promote.check_promotable(mq, TAB)

    def test_draft_round_trip(self):
        issue = {"repo": "ctrueden/tasks", "title": "Do it", "body": "Why:\n\nBecause."}
        self.assertEqual(issue, promote.parse_draft(promote.format_draft(issue)))
        with self.assertRaises(ValueError): promote.parse_draft("title: No repo\n\nBody")

    def test_draft_links_original(self):
        mq = Monoqueue({"rules": {}})
        mq.put(TAB, {"title": "An article"})
        drafted = {"repo": "ctrueden/tasks", "title": "Read it", "body": "Worth reading."}
        with mock.patch.object(agent, "draft_issue", return_value=drafted):
            issue = promote.draft(mq, TAB, why="Because", config={"repo": "ctrueden/tasks"})
        self.assertIn(TAB, issue["body"])
        self.assertEqual("Because", mq.metadata(TAB)["note"])

    def test_create(self):
        mq = Monoqueue({"rules": {}})
        mq.put(TAB, {"title": "An article"})
        mq._score()
        result = mock.Mock(returncode=0, stdout=ISSUE + "\n")
        with mock.patch("monoqueue.promote.subprocess.run", return_value=result) as run:
            url = promote.create(mq, TAB, {"repo": "ctrueden/tasks", "title": "Read it", "body": "B"})
        self.assertEqual(ISSUE, url)
        self.assertEqual(["gh", "issue", "create", "--repo", "ctrueden/tasks"], run.call_args[0][0][:5])
        self.assertEqual("Read it", mq.item(ISSUE)["title"])


class TestAgent(unittest.TestCase):

    def test_github_repo(self):
        self.assertEqual("scijava/jgo", agent.github_repo("https://github.com/scijava/jgo/pull/3"))
        self.assertEqual("scijava/jgo", agent.github_repo("https://github.com/scijava/jgo.git"))
        self.assertIsNone(agent.github_repo("https://github.com/orgs/scijava/projects"))
        self.assertIsNone(agent.github_repo(TAB))

    def test_command_and_args(self):
        mq = Monoqueue({"rules": {}})
        config = {"command": "env FOO=1 claude", "args": "--dangerously-skip-permissions"}
        args, _ = agent.work_command(mq, TAB, config)
        self.assertEqual(["env", "FOO=1", "claude", "--dangerously-skip-permissions"], args[:4])

        # Triage gets the command, but not the interactive arguments.
        output = {"structured_output": {"size": "S"}}
        result = mock.Mock(stdout=json.dumps(output))
        with mock.patch("monoqueue.agent.subprocess.run", return_value=result) as run:
            agent.run("Triage this.", agent.TRIAGE_SCHEMA, config)
        args = run.call_args[0][0]
        self.assertEqual(["env", "FOO=1", "claude", "-p"], args[:4])
        self.assertNotIn("--dangerously-skip-permissions", args)

    def test_triage_stores_result(self):
        mq = Monoqueue({"rules": {"rule1": 'meta/triage/size == "S" -> +5: quick win'}})
        mq.put(TAB, {"title": "An article"})
        result = {"summary": "An article.", "size": "S", "next_action": "Read it.", "actor": "me"}
        with mock.patch.object(agent, "run", return_value=dict(result)) as run:
            agent.triage(mq, TAB)
        self.assertIn("Title: An article", run.call_args[0][0])
        self.assertEqual("S", mq.metadata(TAB)["triage"]["size"])
        mq._score()
        self.assertEqual(6, mq.impact(TAB).value)  # Rules see the triage.


if __name__ == '__main__':
    unittest.main()
