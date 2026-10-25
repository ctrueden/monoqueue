#!/usr/bin/env python
#
# This is free and unencumbered software released into the public domain.
# See the UNLICENSE file for details.
#
# ------------------------------------------------------------------------
# config.py
# ------------------------------------------------------------------------

"""
Monoqueue configuration, from three files in ~/.config/monoqueue:

* rules.conf: the rules scoring action items. Each section is a group of
  rules (e.g. [deadlines]), and each entry within it a rule; the rules of
  all groups run in file order.
* sources.conf: the sources of action items. Each section is a source,
  whose handler (the kind of source) defaults to the section's name.
  This file holds secrets (API keys, passwords), so keep it private.
* settings.conf: everything else. [general] settings, [agent] defaults,
  and settings per action ([triage], [work], [promote], [tune]), which may
  override the [agent] defaults, e.g. a cheaper model for triage.

Rules and settings hold no secrets, so are safe to share, e.g. as dotfiles.

Older versions of monoqueue used one file, ~/.config/monoqueue.conf, which
is still read if the directory does not exist; see migrate.
"""

import configparser
import os
import re
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Tuple

from .log import log

CONFIG_DIR = Path("~/.config/monoqueue").expanduser()
LEGACY_PATH = Path("~/.config/monoqueue.conf").expanduser()

# The sections of settings.conf, rather than sources.
SETTINGS = ("general", "agent", "triage", "work", "promote", "tune")

# Sources renamed since monoqueue.conf, for clarity.
RENAMED = {"firefox": "bookmarks", "scijava": "scijava-team"}

# A comment ending a config line: a # with whitespace on both sides, so that
# values such as "#tag" and "https://example.com/#/route" are left intact.
_EOL_COMMENT = re.compile("\\s+#(\\s.*)?$")

Sections = Dict[str, Dict[str, str]]


def read_config(path: Path) -> configparser.ConfigParser:
    """
    Read a config file, stripping comments that end a line.

    NB: configparser's own inline_comment_prefixes is not used, since it
    would also strip values beginning with #, and would treat ; as a
    comment, which rules may use.
    """
    config = configparser.ConfigParser()
    config.read(path)
    for section in config.sections():
        for key, value in config.items(section, raw=True):
            stripped = _EOL_COMMENT.sub("", value)
            if stripped != value: config.set(section, key, stripped)
    return config


def _sections(config: Mapping) -> Sections:
    return {name: dict(section) for name, section in config.items() if name != "DEFAULT"}


class Config:
    """
    The configuration of a monoqueue: its rules, sources, and settings.
    """

    def __init__(self, rules: Sections = None, sources: Sections = None,
                 settings: Sections = None, rules_path: Optional[Path] = None):
        self.rules = rules or {}
        self.sources = sources or {}
        self.settings = settings or {}
        self.rules_path = rules_path

    @staticmethod
    def load(config_dir: Path = CONFIG_DIR) -> "Config":
        if not config_dir.exists() and LEGACY_PATH.exists():
            log.warning("Using %s; run 'mq migrate-config' to split it up", LEGACY_PATH)
            config = Config.legacy(read_config(LEGACY_PATH))
            config.rules_path = LEGACY_PATH
            return config
        rules_path = config_dir / "rules.conf"
        sources_path = config_dir / "sources.conf"
        if sources_path.exists() and sources_path.stat().st_mode & 0o077:
            log.warning("%s holds secrets, but others can read it; chmod 600 it", sources_path)
        return Config(
            rules=_sections(read_config(rules_path)),
            sources=_sections(read_config(sources_path)),
            settings=_sections(read_config(config_dir / "settings.conf")),
            rules_path=rules_path,
        )

    @staticmethod
    def legacy(config: Mapping) -> "Config":
        """
        Make a configuration from the sections of one monoqueue.conf.
        """
        sections = _sections(config)
        rules = {"rules": {k: v for k, v in sections.pop("rules", {}).items() if k.startswith("rule")}}
        sections.pop("scoring", None)  # Unused, from long ago.
        settings = {name: sections.pop(name) for name in SETTINGS if name in sections}
        return Config(rules=rules, sources=sections, settings=settings)

    def rule_list(self) -> List[Tuple[str, str]]:
        """
        Get the rules, in order, as (expression, consequence) pairs.
        """
        result = []
        for group in self.rules.values():
            for name, rule in group.items():
                expression, arrow, consequence = rule.partition("->")
                if not arrow: raise ValueError(f"Invalid rule {name}: {rule}")
                result.append((expression.strip(), consequence.strip()))
        return result

    def section(self, name: str) -> Dict[str, str]:
        """
        Get the named settings section, or an empty one if there is none.
        """
        return self.settings.get(name, {})

    def action(self, name: str) -> Dict[str, str]:
        """
        Get the settings for an action (e.g. triage): the general settings,
        then the agent defaults, then the action's own settings.
        """
        return {**self.section("general"), **self.section("agent"), **self.section(name)}


def migrate(legacy_path: Path = LEGACY_PATH, config_dir: Path = CONFIG_DIR,
            sources_dir: Optional[Path] = None) -> None:
    """
    Split a monoqueue.conf into rules.conf, sources.conf, and settings.conf,
    keeping its comments. Settings for all agents (about, code_dir) move
    from [agent] to [general]; sources in RENAMED are renamed, along with
    their data files in sources_dir, if given.
    """
    if config_dir.exists():
        raise FileExistsError(f"{config_dir} already exists")
    blocks = _blocks(legacy_path.read_text())

    rules, sources, settings, general = [], [], [], []
    for name, lines in blocks:
        if name == "rules": rules.append(lines)
        elif name in SETTINGS:
            if name == "agent":
                kept = [lines[0]]
                for key, entry in _entries(lines[1:]):
                    (general if key in ("about", "code_dir") else kept).extend(entry)
                lines = kept
            settings.append(lines)
        elif name in RENAMED:
            new = RENAMED[name]
            sources.append([f"[{new}]"] + lines[1:])
            if sources_dir:
                for suffix in (".json", ".status.json"):
                    old_file = sources_dir / f"{name}{suffix}"
                    if old_file.exists(): old_file.rename(sources_dir / f"{new}{suffix}")
        elif name is not None or any(line.strip() for line in lines):
            sources.append(lines)
    if general: settings.insert(0, ["[general]"] + general)

    config_dir.mkdir(parents=True)
    _write(config_dir / "rules.conf", rules)
    _write(config_dir / "settings.conf", settings)
    _write(config_dir / "sources.conf", sources, mode=0o600)


def _blocks(text: str) -> List[Tuple[Optional[str], List[str]]]:
    """
    Split config text into (section name, lines) blocks, each beginning
    with its section header (except a first block before any header).
    """
    blocks = [(None, [])]
    for line in text.splitlines():
        m = re.match("\\[([^\\]]+)\\]\\s*$", line)
        if m: blocks.append((m.group(1), []))
        blocks[-1][1].append(line)
    return blocks


def _entries(lines: List[str]) -> List[Tuple[Optional[str], List[str]]]:
    """
    Split the lines of a section into (key, lines) entries, each with any
    comments before it, and its continuation lines after it.
    """
    entries = [(None, [])]
    pending = []
    for line in lines:
        if not line.strip() or line.lstrip().startswith(("#", ";")):
            pending.append(line)
        elif line[0].isspace() and entries[-1][0] is not None:
            entries[-1][1].extend(pending + [line])
            pending = []
        else:
            entries.append((re.split("\\s*[=:]", line, maxsplit=1)[0].strip(), pending + [line]))
            pending = []
    entries[-1][1].extend(pending)
    return [e for e in entries if e[1]]


def _write(path: Path, blocks: List[List[str]], mode: int = 0o644) -> None:
    text = "\n\n".join(t for t in ("\n".join(lines).strip("\n") for lines in blocks) if t)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(fd, "w") as f:
        f.write(text + "\n" if text else "")
