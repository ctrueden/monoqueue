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

import configparser, datetime, json

from pathlib import Path
from typing import Dict, Optional, List

from . import discourse, firefox, github
from . import time
from .log import log
from .parse import evaluate


HANDLERS = {
    "discourse": discourse.update,
    "firefox": firefox.update,
    "github": github.update,
}


class Monoqueue:
    _DEFAULT_CONFIG_PATH = Path("~/.config/monoqueue.conf").expanduser()
    _DEFAULT_DATA_PATH = Path("~/.local/share/monoqueue/items.json").expanduser()

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
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.data, f, indent=2)

    def urls(self) -> List[str]:
        """
        Get the list of action item URLs, ordered by impact score.
        """
        return sorted(
            self.data,
            key=lambda url: -self.impact(url)
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

    def info(self, url: str) -> Optional[Dict]:
        """
        Get metadata for the given URL.
        """
        return self.data.get(url)

    def defer(self, url: str, timedelta: datetime.timedelta) -> None:
        """
        Defer the given action item for a specified amount of time.
        :param url:
            The URL of the action item to defer.
        :param timedelta:
            datetime.timedelta object indicating deferral time.
        """
        raise RuntimeError("Unimplemented")

    def impact(self, url: str) -> float:
        """
        Get impact score for the given URL.
        :param url:
            The action item URL for which to obtain the impact score.
        :return:
            The impact score.
        """
        info = self.info(url)
        return info["score"]["value"]

    def _score(self):
        log.debug("Scoring action items...")

        # Compute time-sensitive age fields.
        now = time.now()
        for info in self.data.values():
            if "created" in info:
                created_age = time.age(info["created"])
                info["seconds_since_creation"] = created_age.total_seconds()
            if "updated" in info:
                updated_age = time.age(info["updated"])
                info["seconds_since_update"] = updated_age.total_seconds()

        # Initially, each rule has not applied to any action items.
        unused_rules = set(consequence for _, consequence in self.rules)

        for url, info in self.data.items():
            score_value = 1
            score_rules = []
            for expression, consequence in self.rules:
                # Try to apply the rule to this action item.
                applies = evaluate(expression, info)
                if not applies: continue # Rule does not apply.

                # The rule applies. Mark it as used.
                if consequence in unused_rules: unused_rules.remove(consequence)

                # Consequences are of the form:
                #
                #   +3: next-release milestone
                #   ^^  ^
                #   ||  \-- description
                #   |\----- score modification value
                #   \------ operator (+, -, x, or /)
                #
                # So in the above example, the score should increase by 3.
                #
                # If the score modification value is X instead of a number,
                # it is expected the rule application will return the number.
                # For example:
                #
                #   issue/comments -> +X: number of comments
                #
                # The above rule should increase the score by the comment count.

                op = consequence[0]
                sv = consequence[1:consequence.index(":")]

                if sv == "X":
                    # Evaluation result is the score modification value.
                    v = applies
                    # Replace X with the actual number.
                    consequence = f"{op}{applies}{consequence[2:]}"
                else:
                    v = float(sv)

                # Now change the score using the operator and score modification value.
                if op == '+': score_value += v
                elif op == '-': score_value = max(1, score_value - v)
                elif op == 'x': score_value *= v
                elif op == '/': score_value = max(1, score_value / v)
                else: raise RuntimeError(f"Invalid rule consequence: {consequence}")

                # Record the consequence on this item's list of applied rules.
                score_rules.append(consequence)

            info["score"] = {"value": score_value, "rules": score_rules}

        # Warn about rules that never applied to an action item.
        for _, consequence in self.rules:
            if consequence in unused_rules:
                log.warning(f"Irrelevant rule: %s", consequence)
