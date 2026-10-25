#!/usr/bin/env python
#
# This is free and unencumbered software released into the public domain.
# See the UNLICENSE file for details.
#
# ------------------------------------------------------------------------
# test_config.py
# ------------------------------------------------------------------------

import tempfile
import unittest
from pathlib import Path

from monoqueue import Monoqueue, config
from monoqueue.config import Config

LEGACY = """\
[rules]
# Rules run in order.
rule01 = bookmark -> +20: action bookmark  # A comment.
rule02 = tabs     -> +3: open in a tab

[firefox]
folder = ACTION

[github]
token = secret
query = state:open+user:me

[scijava]
dev_id = me

[agent]
command = claude
# About me, for agents.
about = I maintain
  some software.
model = sonnet
code_dir = ~/code

[promote]
repo = me/tasks
"""


class TestConfig(unittest.TestCase):

    def test_legacy(self):
        c = Config.legacy({
            "rules": {"rule1": "a -> +1: a", "other": "ignored"},
            "github": {"query": "q"},
            "agent": {"model": "sonnet"},
            "scoring": {},
        })
        self.assertEqual([("a", "+1: a")], c.rule_list())
        self.assertEqual(["github"], list(c.sources))
        self.assertEqual({"model": "sonnet"}, c.section("agent"))

    def test_rule_groups_run_in_order(self):
        c = Config(rules={
            "deadlines": {"due": "seconds_until_due < 0 -> +20: overdue"},
            "community": {"first": "issue/draft -> /2: draft", "second": "tabs -> +3: tab"},
        })
        self.assertEqual(["seconds_until_due < 0", "issue/draft", "tabs"],
                         [expression for expression, _ in c.rule_list()])
        with self.assertRaises(ValueError):
            Config(rules={"g": {"bad": "no arrow"}}).rule_list()

    def test_action_overrides_agent_and_general(self):
        c = Config(settings={
            "general": {"about": "Me", "code_dir": "~/src"},
            "agent": {"model": "sonnet", "command": "claude"},
            "triage": {"model": "haiku"},
        })
        self.assertEqual({"about": "Me", "code_dir": "~/src", "model": "haiku", "command": "claude"},
                         c.action("triage"))
        self.assertEqual("sonnet", c.action("work")["model"])

    def test_migrate(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            legacy = tmp / "monoqueue.conf"
            legacy.write_text(LEGACY)
            sources_dir = tmp / "sources"
            sources_dir.mkdir()
            (sources_dir / "firefox.json").write_text("{}")
            config_dir = tmp / "monoqueue"
            config.migrate(legacy, config_dir, sources_dir)

            rules = (config_dir / "rules.conf").read_text()
            self.assertIn("# Rules run in order.", rules)
            settings = (config_dir / "settings.conf").read_text()
            self.assertTrue(settings.startswith("[general]\n# About me, for agents.\nabout = I maintain\n  some software.\n"))
            self.assertIn("code_dir = ~/code\n\n[agent]\ncommand = claude\nmodel = sonnet\n", settings)
            self.assertIn("ACTION\n\n[github]", (config_dir / "sources.conf").read_text())
            sources = (config_dir / "sources.conf").read_text()
            self.assertIn("[bookmarks]\nfolder = ACTION", sources)
            self.assertIn("[scijava-team]", sources)
            self.assertNotIn("secret", rules + settings)
            self.assertEqual(0o600, (config_dir / "sources.conf").stat().st_mode & 0o777)
            self.assertTrue((sources_dir / "bookmarks.json").exists())

            c = Config.load(config_dir)
            self.assertEqual(["bookmarks", "github", "scijava-team"], list(c.sources))
            self.assertEqual("+20: action bookmark", c.rule_list()[0][1])
            self.assertEqual("I maintain\nsome software.", c.action("promote")["about"])
            self.assertEqual("me/tasks", c.action("promote")["repo"])
            self.assertEqual(config_dir / "rules.conf", c.rules_path)

            with self.assertRaises(FileExistsError):
                config.migrate(legacy, config_dir)

    def test_reload_rules(self):
        mq = Monoqueue(Config(rules={"g": {"r": "tabs -> +3: tab"}}))
        mq.put("https://example.com/a", {"tabs": [{}]})
        mq._score()
        self.assertEqual(4, mq.impact("https://example.com/a").value)
        mq.reload_rules(Config(rules={"g": {"r": "tabs -> +9: tab"}}))
        self.assertEqual(10, mq.impact("https://example.com/a").value)


if __name__ == '__main__':
    unittest.main()
