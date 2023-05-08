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
from typing import Any, Dict, Optional, List

from . import discourse, firefox, github
from . import time
from .log import log
from .parse import evaluate


HANDLERS = {
    "discourse": discourse.update,
    "firefox": firefox.update,
    "github": github.update,
}


class ImpactScore:
    def __init__(self, value, rules):
        self.value = value
        self.rules = rules


class Monoqueue:
    _DEFAULT_CONFIG_PATH = Path("~/.config/monoqueue.conf").expanduser()
    _DEFAULT_ITEMS_PATH = Path("~/.local/share/monoqueue/items.json").expanduser()
    _DEFAULT_METADATA_PATH = Path("~/.local/share/monoqueue/metadata.json").expanduser()

    def __init__(self, config: Dict = None):
        if config is None:
            config = configparser.ConfigParser()
            config.read(Monoqueue._DEFAULT_CONFIG_PATH)
        self.config = config
        self.items = {}
        self._impact = {}
        self._metadata = {}
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

    def load(self,
        items_path: Path = _DEFAULT_ITEMS_PATH,
        metadata_path: Path = _DEFAULT_METADATA_PATH
    ) -> None:
        self.items = self._load(items_path)
        self._metadata = self._load(metadata_path)
        if self.items: self._score()

    def save(self,
        items_path: Path = _DEFAULT_ITEMS_PATH,
        metadata_path: Path = _DEFAULT_METADATA_PATH
    ) -> None:
        self._save(self.items, items_path)
        self._save(self._metadata, metadata_path)

    def urls(self, active_only=True) -> List[str]:
        """
        Get the list of action item URLs, ordered by impact score.
        """
        urls = []
        urls.extend(
            (url for url in self.items if self.active(url))
            if active_only
            else self.items
        )
        urls.sort(key=lambda url: self.impact(url).value, reverse=True)
        return urls

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

            log.debug("Action item count -> %d", len(self.items))

        # Recalculate item scores.
        self._score()

    def item(self, url: str) -> Optional[Dict[str, Any]]:
        """
        Get action item data for the given URL.

        This information is retrieved from remote sources,
        unlike mq.metadata(url), which is locally managed info.

        :param url:
            The URL of the action item data to retrieve.
        :return:
            Information relating to the action item, or None if no such item.
        """
        return self.items.get(url)

    def metadata(self, url: str) -> Dict[str, Any]:
        """
        Get metadata (e.g. deferrals) for the given URL.

        Unlike mq.item(url), metadata is managed locally
        rather than being retrieved from remote sources.

        :param url:
            The URL of the action item metadata to retrieve.
        :return:
            Metadata relating to the action item.
        """
        if not url in self._metadata:
            self._metadata[url] = {}
        return self._metadata[url]

    def defer(self, url: str, timedelta: datetime.timedelta) -> None:
        """
        Defer the given action item for a specified amount of time.
        :param url:
            The URL of the action item to defer.
        :param timedelta:
            datetime.timedelta object indicating deferral time.
        """
        metadata = self.metadata(url)
        metadata["deferred_at"] = time.string(time.now())
        metadata["deferred_until"] = time.string(timedelta)

    def active(self, url: str) -> bool:
        """
        Get whether the given URL's action item is currently active.
        If it was previously deferred until later, and the deferral
        time has not yet come to pass, then the URL will be inactive.
        :param url:
            The action item URL to check if active.
        :return:
            True if the action item is currently active, False if not.
        """
        if url not in self.items: return False
        metadata = self.metadata(url)
        if metadata is None or "deferred_until" not in metadata: return True

        item = self.item(url)
        if "deferred_at" in metadata and "updated" in metadata:
            # Check whether item has changed since deferral occurred.
            deferred_at = time.str2dt(metadata["deferred_at"])
            updated = time.str2dt(item["updated"])
            if updated > deferred_at: return True

        # Check whether the deferral time has already passed.
        deferred_until = time.str2dt(metadata["deferred_until"])
        return time.now() >= deferred_until

    def impact(self, url: str) -> ImpactScore:
        """
        Get impact score for the given URL.
        :param url:
            The action item URL for which to obtain the impact score.
        :return:
            The impact score.
        """
        return self._impact.get(url)

    def _load(self, path: Path) -> Dict[str, Any]:
        log.debug("Loading %s...", path)

        if path is None or not path.exists():
            log.debug("No existing items at %s", path)
            return {}
        with open(path) as f:
            return json.load(f)

    def _save(self, data: Dict[str, Any], path: Path) -> None:
        log.debug("Saving %s...", path)

        if data is None or path is None: return
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    def _score(self):
        log.debug("Scoring action items...")

        # Compute time-sensitive age fields.
        now = time.now()
        for item in self.items.values():
            if "created" in item:
                created_age = time.age(item["created"])
                item["seconds_since_creation"] = created_age.total_seconds()
            if "updated" in item:
                updated_age = time.age(item["updated"])
                item["seconds_since_update"] = updated_age.total_seconds()

        # Initially, each rule has not applied to any action items.
        unused_rules = set(consequence for _, consequence in self.rules)

        self._impact.clear()
        for url, info in self.items.items():
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
                smv = consequence[1:consequence.index(":")]

                if smv == "X":
                    # Score mod value is the rule evaluation result.
                    smv = float(applies)
                    # Replace X with the actual number.
                    consequence = f"{op}{applies}{consequence[2:]}"
                else:
                    # Score mod value is a constant declared in the consequence.
                    smv = float(smv)

                # Now change the score using the operator and score modification value.
                if op == '+': score_value += smv
                elif op == '-': score_value = max(1, score_value - smv)
                elif op == 'x': score_value *= smv
                elif op == '/': score_value = max(1, score_value / smv)
                else: raise RuntimeError(f"Invalid rule consequence: {consequence}")

                # Record the consequence on this item's list of applied rules.
                score_rules.append(consequence)

            self._impact[url] = ImpactScore(score_value, score_rules)

        # Warn about rules that never applied to an action item.
        for _, consequence in self.rules:
            if consequence in unused_rules:
                log.debug(f"Irrelevant rule: %s", consequence)
