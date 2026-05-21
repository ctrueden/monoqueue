#!/usr/bin/env python
#
# This is free and unencumbered software released into the public domain.
# See the UNLICENSE file for details.
#
# ------------------------------------------------------------------------
# github.py
# ------------------------------------------------------------------------

"""
Routines to download and organize information from GitHub.
"""

import datetime
import json
import time
from pathlib import Path

import requests

from .log import log

_SEARCH_BASE = "https://api.github.com/search/issues"
_DELAY = 7
_MAX_PAGES = 200

DEFAULT_CACHE_DIR = Path("~/.cache/monoqueue/github").expanduser()
DEFAULT_MAX_AGE = 14400  # 4 hours


def update(mq, config):
    orgs, users = _parse_owners(config["query"])
    progress = None
    if mq.progress:
        def progress(fetched, total):
            mq.progress(True)
    items = fetch_items(orgs=orgs, users=users, token=config.get("token"), progress=progress)
    if mq.progress:
        mq.progress(None)
    for issue in items:
        url = issue["html_url"]
        mq.items.setdefault(url, {}).update({
            "title": issue["title"],
            "created": issue["created_at"],
            "updated": issue["updated_at"],
            "issue": issue,
        })


def fetch_items(
    orgs=(),
    users=(),
    token=None,
    cache_dir=DEFAULT_CACHE_DIR,
    max_age=DEFAULT_MAX_AGE,
    refresh=False,
    progress=None,
):
    """Fetch open GitHub issues/PRs for the given orgs and users.

    Results are cached to disk under cache_dir/<owner>/ as per-repo JSON
    files and refreshed incrementally once the cache is older than max_age
    seconds. Pass refresh=True to discard the cache and re-fetch everything.
    """
    cache_dir = Path(cache_dir)
    orgs, users = set(orgs), set(users)
    if not orgs and not users:
        return []

    # Record before the first HTTP request so the next incremental window
    # doesn't miss items updated while this fetch is in progress.
    fetch_start = _utcnow()

    if not refresh:
        cached_items, oldest = _load_cache(cache_dir, orgs, users)
        if oldest is not None:
            age = (_parse_ts(fetch_start) - _parse_ts(oldest)).total_seconds()
            if age <= max_age:
                items = list(cached_items.values())
                if progress:
                    progress(len(items), len(items))
                return items
            since = oldest
        else:
            cached_items, since = {}, None
    else:
        cached_items, since = {}, None

    ghi = GitHubIssues(token=token, progress=progress)
    ghi.download(_build_query(orgs, users, since))

    for item in ghi.issues:
        item_id = str(item["id"])
        if item.get("state") == "open":
            cached_items[item_id] = item
        else:
            cached_items.pop(item_id, None)

    _write_cache(cache_dir, orgs, users, cached_items, fetch_start)
    return list(cached_items.values())


def _parse_owners(query):
    orgs, users = set(), set()
    for term in query.replace("+", " ").split():
        if term.startswith("org:"):
            orgs.add(term[4:])
        elif term.startswith("user:"):
            users.add(term[5:])
    return orgs, users


def _build_query(orgs, users, since=None):
    parts = sorted(f"org:{o}" for o in orgs) + sorted(f"user:{u}" for u in users)
    parts.append(f"updated:>{since}" if since else "is:open")
    return "+".join(parts)


def _utcnow():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_ts(ts):
    return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _load_cache(cache_dir, orgs, users):
    """Return (items_dict, oldest_fetched_at) for the given owners.

    oldest_fetched_at is None if any owner has no _meta.json, signalling
    that a full fetch is needed.
    """
    items, oldest = {}, None
    for owner in sorted(orgs | users):
        meta_file = cache_dir / owner / "_meta.json"
        if not meta_file.exists():
            return {}, None
        meta = json.loads(meta_file.read_text())
        ts = meta.get("fetched_at")
        if not ts:
            return {}, None
        if oldest is None or ts < oldest:
            oldest = ts
        for repo_file in sorted((cache_dir / owner).glob("*.json")):
            if repo_file.name != "_meta.json":
                items.update(json.loads(repo_file.read_text()).get("items", {}))
    return items, oldest


def _write_cache(cache_dir, orgs, users, all_items, fetched_at):
    """Write per-repo JSON files and per-owner _meta.json files."""
    repo_items: dict[tuple[str, str], dict] = {}
    for item_id, item in all_items.items():
        slug = item["repository_url"].removeprefix("https://api.github.com/repos/")
        owner, _, repo = slug.partition("/")
        repo_items.setdefault((owner, repo), {})[item_id] = item

    for owner in orgs | users:
        d = cache_dir / owner
        d.mkdir(parents=True, exist_ok=True)

        # Include repos that previously had files so newly-empty ones get
        # overwritten with {} rather than left with stale data.
        repos = {f.stem for f in d.glob("*.json") if f.name != "_meta.json"}
        repos |= {repo for (o, repo) in repo_items if o == owner}

        for repo in repos:
            (d / f"{repo}.json").write_text(
                json.dumps(
                    {"fetched_at": fetched_at, "items": repo_items.get((owner, repo), {})},
                    indent=2,
                )
            )
        (d / "_meta.json").write_text(json.dumps({"fetched_at": fetched_at}, indent=2))


class GitHubIssues:

    def __init__(self, items=None, token=None, progress=None):
        self._token = token
        self.issues = [] if items is None else items
        self._progress = progress

    def load(self, filepath):
        """Load issues from the given JSON file."""
        with open(filepath) as f:
            self.issues.extend(json.loads(f.read()))

    def save(self, filepath):
        """Save issues to the given JSON file."""
        with open(filepath, "w") as f:
            json.dump(self.issues, f, sort_keys=True, indent=4)

    def download(self, query):
        """Download issues from GitHub according to the given query."""
        url = self._search_url(query)
        for _ in range(_MAX_PAGES):
            url, total = self._download_page(url, query)
            if self._progress:
                self._progress(len(self.issues), total)
            if not url:
                break
            time.sleep(_DELAY)

    def _download_page(self, url, query):
        headers = {"User-Agent": "monoqueue"}
        if self._token:
            headers["Authorization"] = f"token {self._token}"
        log.debug("Downloading %s", url)
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        self.issues.extend(data["items"])
        total = data.get("total_count", len(self.issues))
        next_url = resp.links.get("next", {}).get("url")
        if not next_url and total > 1000 and data["items"]:
            # Work around GitHub's 1000-result search cap.
            next_url = self._search_url(f"{query}+created:>{data['items'][-1]['created_at']}")
        return next_url, total

    @staticmethod
    def _search_url(query):
        return f"{_SEARCH_BASE}?q={query}&sort=created&order=asc&per_page=100"
