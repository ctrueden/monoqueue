#!/usr/bin/env python
#
# This is free and unencumbered software released into the public domain.
# See the UNLICENSE file for details.
#
# ------------------------------------------------------------------------
# __init__.py
# ------------------------------------------------------------------------

"""
The monoqueue data structure with core business logic.
"""

import configparser, datetime, json, re, sys

from pathlib import Path
from typing import Dict, Optional, List

from . import discourse, firefox, github
from .log import log
from .parse import evaluate


HANDLERS = {
    "discourse": discourse.update,
    "firefox": firefox.update,
    "github": github.update,
}


def now() -> datetime.datetime:
    """
    Get the current date, in UTC.
    """
    return datetime.datetime.now(tz=datetime.timezone.utc)


def s2dt(timestamp: str) -> datetime.datetime:
    """
    Parse a string to a datetime object.
    """
    # Credit: https://stackoverflow.com/a/969324/1207769
    if re.match("\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\\.\d+Z$", timestamp):
        # GitHub style, without millisecond.
        return datetime.datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%S.%f%z")
    if re.match("\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", timestamp):
        # Discourse style, with millisecond.
        return datetime.datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%S%z")
    raise ValueError(f"Weird timestamp: {timestamp}")


class Monoqueue:
    _DEFAULT_CONFIG_PATH = Path("~/.config/monoqueue.conf").expanduser()
    _DEFAULT_DATA_PATH = Path("~/.local/share/monoqueue.data").expanduser()

    def __init__(self, config: Dict = None):
        if config is None:
            config = configparser.ConfigParser()
            config.read(Monoqueue._DEFAULT_CONFIG_PATH)
        self.config = config
        self.data = {}
        self.progress = None

        # load rules from config
        self.rules = []
        for k, v in config["rules"].items():
            if not k.startswith("rule"): continue
            arrow = v.find("->")
            if not arrow:
                raise ValueError(f"Invalid rule: {v}")
            expression = v[:arrow].strip()
            consequence = v[arrow+2:].strip()
            self.rules.append((expression, consequence))
        log.debug("Parsed %d rules", len(self.rules))

    def load(self, path: Path = _DEFAULT_DATA_PATH) -> None:
        if path.exists():
            with open(path) as f:
                self.data = json.load(f)
            self._score()
        else:
            log.debug("No existing data at %s", path)

    def save(self, path: Path = _DEFAULT_DATA_PATH) -> None:
        with open(path, "w") as f:
            json.dump(self.data, f, indent=2)

    def urls(self, backlog: bool = False) -> List[str]:
        """
        Get the list of action item URLs, ordered by impact score.

        :param backlog:
            If True, scores older items more highly.
            If False, scores newer items more highly.
            The default is False.
        """
        return sorted(
            self.data,
            key=lambda url: -self.impact(url, backlog=backlog)
        )

    def update(self) -> None:
        """
        Update the queue from its sources.

        :raise RuntimeError: If something goes wrong.
        """

        for section, config in self.config.items():
            if section in ("DEFAULT", "rules", "scoring"): continue

            config["source"] = section
            handler = config.get("handler", section)

            log.info("Updating %s...", section)

            if not handler in HANDLERS:
                raise f"Unsupported source type: {handler}"

            # Execute the handler's update function.
            update = HANDLERS[handler]
            if update is not None: update(self, config)

            log.debug("Action item count -> %d", len(self.data))

        # Persist the updated queue to disk.
        self.save()

        # Recalculate item scores.
        self._score()

    def defer(self, url: str, timedelta: datetime.timedelta):
        """
        Defer the given action item for a specified amount of time.
        :param url:
            The URL of the action item to defer.
        :param timedelta:
            datetime.timedelta object indicating deferral time.
        """
        raise RuntimeError("Unimplemented")

    def info(self, url: str) -> Optional[Dict]:
        """
        Get metadata for the given URL.
        """
        return self.data.get(url)

    def impact(self, url: str, backlog: bool = False):
        """
        Get impact score for the given URL.
        :param url:
            The action item URL for which to calculate impact score.
        :param backlog:
            If True, scores older items more highly.
            If False, scores newer items more highly.
            The default is False.
        """
        info = self.info(url)
        score = info["score"]["value"]
        timedelta = now() - s2dt(info["updated"])
        days_ago: float = timedelta.total_seconds() / 86400
        # backlog tackle: multiply times number of days old
        # rapid response: divide by number of days old
        one_day_multiplier = (
            self.config["scoring"].get("one_day_multiplier", 10)
            if "scoring" in self.config
            else 10
        )
        factor = 1 + (days_ago if backlog else one_day_multiplier / days_ago)
        final = score * factor**2
        log.debug(f"%s age=%f, factor=%f, final=%f", info["title"], days_ago, factor, final)
        return final

    def _score(self):
        log.debug("Scoring action items...")

        for url, info in self.data.items():
            score_value = 1
            score_rules = []
            for expression, consequence in self.rules:
                # TODO: Add comments explaining this mess.
                applies = evaluate(expression, info)
                if not applies: continue
                score_rules.append(consequence)
                op = consequence[0]
                sv = consequence[1:consequence.index(":")]
                v = applies if sv == "X" else float(sv)
                if op == '+': score_value += v
                elif op == '-': score_value -= v
                elif op == 'x': score_value *= v
                elif op == '/': score_value /= v
                else: raise RuntimeError(f"Invalid rule consequence: {consequence}")

            info["score"] = {"value": score_value, "rules": score_rules}

        # Warn about rules that never applied to an action item.
        used_rules = set(rule for info in self.data.values() for rule in info["score"]["rules"])
        for _, consequence in self.rules:
            if not consequence in used_rules:
                log.warning(f"Irrelevant rule: %s", consequence)
