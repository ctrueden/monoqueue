#!/usr/bin/env python
#
# This is free and unencumbered software released into the public domain.
# See the UNLICENSE file for details.
#
# ------------------------------------------------------------------------
# notifications.py
# ------------------------------------------------------------------------

"""
Routines to download your unread GitHub notifications.

Only notifications aimed at you personally become action items: by
default mentions, review requests, and assignments, rather than mere
activity on repositories you watch. Each item gets a notification
field, for use in rules such as:

    notification/reason == "review_requested" -> +10: review requested
"""

import re

import requests

from .github import gh_token
from .log import log

DEFAULT_REASONS = "mention, team_mention, review_requested, assign"

_API_URL = "https://api.github.com/notifications"
_MAX_PAGES = 20


def update(mq, config):
    reasons = {r.strip() for r in config.get("reasons", DEFAULT_REASONS).split(",") if r.strip()}
    token = config.get("token") or gh_token()
    if not token:
        raise RuntimeError("No GitHub token: configure one, or log in with gh")

    for notification in fetch(token):
        if notification.get("reason") not in reasons: continue
        subject = notification.get("subject", {})
        mq.put(html_url(notification), {
            "title": subject.get("title"),
            "updated": notification.get("updated_at"),
            "notification": {
                "id": notification.get("id"),
                "reason": notification.get("reason"),
                "type": subject.get("type"),
                "repo": notification.get("repository", {}).get("full_name"),
                "unread": notification.get("unread"),
            },
        })


def fetch(token):
    """
    Fetch all unread notifications.
    """
    session = requests.Session()
    session.headers.update({
        "User-Agent": "monoqueue",
        "Accept": "application/vnd.github+json",
        "Authorization": f"token {token}",
    })
    notifications = []
    url = f"{_API_URL}?per_page=50"
    for _ in range(_MAX_PAGES):
        log.debug("Downloading %s", url)
        response = session.get(url, timeout=30)
        response.raise_for_status()
        notifications.extend(response.json())
        url = response.links.get("next", {}).get("url")
        if not url: break
    return notifications


def html_url(notification):
    """
    Get the web URL a notification is about, e.g. the issue or PR.

    The API gives only API URLs, so map them to their web equivalents,
    falling back to the repository for subjects without one.
    """
    repo_url = notification.get("repository", {}).get("html_url", "")
    api_url = notification.get("subject", {}).get("url") or ""
    m = re.match("https://api\\.github\\.com/repos/([^/]+/[^/]+)/(issues|pulls|commits)/(\\w+)$", api_url)
    if m:
        repo, kind, ident = m.groups()
        kind = {"issues": "issues", "pulls": "pull", "commits": "commit"}[kind]
        return f"https://github.com/{repo}/{kind}/{ident}"
    if notification.get("subject", {}).get("type") == "Release":
        return f"{repo_url}/releases"
    return repo_url
