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

import configparser
import datetime
import json
import traceback
from pathlib import Path
from typing import Any, Dict, Optional, List
from urllib.parse import urlsplit

from . import discourse, firefox, github, scijava
from . import time, urls
from .log import log
from .parse import evaluate

HANDLERS = {
    "discourse": discourse.update,
    "firefox": firefox.update,
    "github": github.update,
    "scijava": scijava.update,
    "tabs": firefox.update_tabs,
}


def merge_item(item: Dict[str, Any], data: Dict[str, Any]) -> None:
    """
    Merge data about an action item into the item.

    The earliest created timestamp, the latest updated timestamp, and the
    first title win; other fields from data replace those of the item.
    """
    data = dict(data)
    for key, pick in (("created", min), ("updated", max)):
        if item.get(key) and data.get(key):
            data[key] = pick(item[key], data[key], key=time.str2dt)
    if item.get("title"): data.pop("title", None)
    item.update(data)


class Source:
    """
    Collects the action items of one source during an update.

    Source handlers receive one of these, and call its put method to
    report action items, just like Monoqueue.put. When the handler
    succeeds, the items are saved to the source's own file, which is then
    merged with the other sources' files into the queue. When it fails,
    that source's file from its last success remains in use.
    """

    def __init__(self, mq: "Monoqueue", name: str):
        self.mq = mq
        self.name = name
        self.items: Dict[str, Dict[str, Any]] = {}
        self.progress = mq.progress

    def normalize(self, url: str) -> str:
        return self.mq.normalize(url)

    def put(self, url: str, data: Dict[str, Any], weak: bool = False) -> str:
        """
        Report information about an action item; see Monoqueue.put.
        """
        url = self.normalize(url)
        item = self.items.setdefault(url, {"weak": True} if weak else {})
        if not weak: item.pop("weak", None)
        merge_item(item, data)
        return url


class ImpactScore:
    def __init__(self, value, rules):
        self.value = value
        self.rules = rules


class Monoqueue:
    _DEFAULT_CONFIG_PATH = Path("~/.config/monoqueue.conf").expanduser()
    _DEFAULT_ITEMS_PATH = Path("~/.local/share/monoqueue/items.json").expanduser()
    _DEFAULT_METADATA_PATH = Path("~/.local/share/monoqueue/metadata.json").expanduser()
    _DEFAULT_SOURCES_DIR = Path("~/.local/share/monoqueue/sources").expanduser()

    def __init__(self, config: Dict = None):
        if config is None:
            config = configparser.ConfigParser()
            config.read(Monoqueue._DEFAULT_CONFIG_PATH)
        self.config = config
        self.items = {}
        self._impact = {}
        self._metadata = {}
        self.progress = None
        self.sources_dir = Monoqueue._DEFAULT_SOURCES_DIR

        # load rules from config
        self.rules = []
        for k, v in config["rules"].items():
            if not k.startswith("rule"): continue
            arrow = v.find("->")
            if not arrow:
                raise ValueError(f"Invalid rule: {v}")
            expression = v[:arrow].strip()
            consequence = v[arrow + 2:].strip()
            self.rules.append((expression, consequence))
        log.debug("Parsed %d rules", len(self.rules))

        # Discourse forums need special URL normalization.
        self.discourse_hosts = set(urls.DISCOURSE_HOSTS)
        for section, section_config in config.items():
            if section_config.get("handler") == "discourse":
                baseurl = section_config.get("baseurl", f"https://{section}")
                self.discourse_hosts.add(urlsplit(baseurl).netloc.lower())

    def load(self,
        items_path: Path = _DEFAULT_ITEMS_PATH,
        metadata_path: Path = _DEFAULT_METADATA_PATH
    ) -> None:
        self.items = self._load(items_path)
        self._metadata = {}
        for url, metadata in self._load(metadata_path).items():
            # Metadata from older versions may be keyed by unnormalized URLs.
            self.metadata(url).update(metadata)
        if self.items: self._score()

    def save(self,
        items_path: Optional[Path] = _DEFAULT_ITEMS_PATH,
        metadata_path: Optional[Path] = _DEFAULT_METADATA_PATH
    ) -> None:
        self._save(self.items, items_path)
        self._save(self._metadata, metadata_path)

    def urls(self, active_only=True) -> List[str]:
        """
        Get the list of action item URLs, ordered by impact score,
        except that alerts (e.g. failing sources) always come first.
        """
        urls = []
        urls.extend(
            (url for url in self.items if self.active(url))
            if active_only
            else self.items
        )
        urls.sort(
            key=lambda url: (bool(self.items[url].get("alert")), self.impact(url).value),
            reverse=True,
        )
        return urls

    def sources(self) -> List[str]:
        """
        Get the names of the configured sources, in configuration order.
        """
        return [
            section for section in self.config
            if section not in ("DEFAULT", "rules", "scoring")
        ]

    def update(self, sources: Optional[List[str]] = None) -> None:
        """
        Update the queue from its sources.

        Each source is fetched separately, and its items saved to its own
        file beneath sources_dir. A source that fails keeps the items
        from its last success, and gets an alert item describing the
        failure. Then the items of all sources are merged into the queue.

        :param sources:
            Names of the sources to fetch, or None to fetch all of them.
            Either way, the items of all sources are merged.
        """
        for section in self.sources():
            if sources and section not in sources: continue
            self._update_source(section, self.config[section])

        self.items = self._merge_sources()
        self._score()

    def _update_source(self, section: str, config) -> None:
        config["source"] = section
        handler = config.get("handler", section)
        log.info("Updating %s...", section)

        status_path = self.sources_dir / f"{section}.status.json"
        status = self._load(status_path)
        now = time.string(int(time.now().timestamp()))
        try:
            if handler not in HANDLERS:
                raise ValueError(f"Unsupported source type: {handler}")
            source = Source(self, section)
            HANDLERS[handler](source, config)
        except Exception as e:
            log.error("Source %s failed: %s", section, e)
            if status.get("ok", True): status["failing_since"] = now
            status.update({
                "ok": False,
                "last_attempt": now,
                "error": f"{type(e).__name__}: {e}",
                "traceback": traceback.format_exc(),
            })
        else:
            log.debug("Source %s -> %d items", section, len(source.items))
            self._save(
                {"source": section, "fetched": now, "items": source.items},
                self.sources_dir / f"{section}.json",
            )
            status = {"ok": True, "last_attempt": now, "last_success": now}
        self._save(status, status_path)

    def _merge_sources(self) -> Dict[str, Dict[str, Any]]:
        """
        Merge the saved items of all configured sources, in configuration
        order. Weak items (which only annotate) are merged last, and only
        into items that some other source reported.
        """
        items = {}
        weak = []
        for name in self.sources():
            data = self._load(self.sources_dir / f"{name}.json")
            for url, item in data.get("items", {}).items():
                url = self.normalize(url)
                if item.get("weak"):
                    weak.append((name, url, item))
                    continue
                merged = items.setdefault(url, {})
                merge_item(merged, item)
                merged.setdefault("sources", []).append(name)

            status = self._load(self.sources_dir / f"{name}.status.json")
            if status and not status.get("ok", True):
                items[f"monoqueue:source/{name}"] = self._failure_item(name, status)

        for name, url, item in weak:
            if url not in items: continue
            merge_item(items[url], {k: v for k, v in item.items() if k != "weak"})
            items[url]["sources"].append(name)

        return items

    @staticmethod
    def _failure_item(name: str, status: Dict[str, Any]) -> Dict[str, Any]:
        last_success = status.get("last_success")
        return {
            "title": f"Fix monoqueue source: {name}",
            "description": (
                f"{status.get('error')}\n\n"
                f"Failing since {status.get('failing_since')}; "
                f"last attempt {status.get('last_attempt')}; "
                f"last success {last_success or 'never'}.\n"
                + (
                    "Until it is fixed, the queue uses this source's items from its last success."
                    if last_success else
                    "This source has no items in the queue until it succeeds."
                )
                + f"\n\n{status.get('traceback', '')}"
            ),
            "created": status.get("failing_since"),
            "updated": status.get("failing_since"),
            "alert": True,
            "sources": ["monoqueue"],
        }

    def normalize(self, url: str) -> str:
        """
        Normalize the given URL, so that equivalent URLs compare equal.
        See monoqueue.urls.normalize for details.
        """
        return urls.normalize(url, self.discourse_hosts)

    def put(self, url: str, data: Dict[str, Any], weak: bool = False) -> str:
        """
        Merge data from a source into the action item for the given URL.

        The URL is normalized first, so that equivalent URLs from different
        sources (e.g. a browser tab and a GitHub issue) become one item.
        When the item already exists, the earliest created timestamp,
        the latest updated timestamp, and the first title win.

        :param url:
            The URL of the action item.
        :param data:
            Information about the action item, such as title, created and
            updated timestamps, and source-specific details.
        :param weak:
            If True, only annotate an existing item; never create one.
        :return:
            The normalized URL.
        """
        url = self.normalize(url)
        if weak and url not in self.items: return url
        merge_item(self.items.setdefault(url, {}), data)
        return url

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
        return self._metadata.setdefault(self.normalize(url), {})

    def defer(self, url: str, until: datetime.datetime) -> None:
        """
        Defer the given action item for a specified amount of time.
        :param url:
            The URL of the action item to defer.
        :param until:
            datetime.datetime object indicating deferral time.
        """
        metadata = self.metadata(url)
        metadata["deferred_at"] = time.string(time.now())
        metadata["deferred_until"] = time.string(until)

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
        if "deferred_at" in metadata and "updated" in item:
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

    @staticmethod
    def _load(path: Path) -> Dict[str, Any]:
        log.debug("Loading %s...", path)

        if path is None or not path.exists():
            log.debug("No existing items at %s", path)
            return {}
        with open(path) as f:
            return json.load(f)

    @staticmethod
    def _save(data: Dict[str, Any], path: Path) -> None:
        log.debug("Saving %s...", path)

        if data is None or path is None: return
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    def _score(self):
        log.debug("Scoring action items...")

        # Compute time-sensitive age fields.
        for item in self.items.values():
            if "created" in item:
                created_age = time.age(item["created"])
                item["seconds_since_creation"] = created_age.total_seconds()
            if "updated" in item:
                updated_age = time.age(item["updated"])
                item["seconds_since_update"] = updated_age.total_seconds()
            accessed = [t["last_accessed"] for t in item.get("tabs", []) if t.get("last_accessed")]
            if accessed:
                tab_age = time.age(max(accessed, key=time.str2dt))
                item["seconds_since_tab_access"] = tab_age.total_seconds()

        # Initially, each rule has not applied to any action items.
        unused_rules = set(consequence for _, consequence in self.rules)

        self._impact.clear()
        for url, info in self.items.items():
            score_value = 1
            score_rules = []
            for expression, consequence in self.rules:
                # Try to apply the rule to this action item.
                applies = evaluate(expression, info)
                if not applies: continue  # Rule does not apply.

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
