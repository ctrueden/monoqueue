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

Notifications stay unread on GitHub until read or marked done, even once
their issue or PR is closed, or once you are no longer asked. So each
notification's issue or PR is checked too: review requests and assignments
are dropped once moot (closed, merged, or no longer requesting or assigning
you), while mentions are kept, with the state recorded, e.g.:

    notification/state != "open"         -> /4: closed
    notification/others_requested >= 3   -> /2: one of many reviewers
"""

import json
import re

import requests

from .github import gh_token
from .log import log

DEFAULT_REASONS = "mention, team_mention, review_requested, assign"

_API_URL = "https://api.github.com/notifications"
_GRAPHQL_URL = "https://api.github.com/graphql"
_MAX_PAGES = 20


def update(mq, config):
    reasons = {r.strip() for r in config.get("reasons", DEFAULT_REASONS).split(",") if r.strip()}
    token = config.get("token") or gh_token()
    if not token:
        raise RuntimeError("No GitHub token: configure one, or log in with gh")

    personal = [n for n in fetch(token) if n.get("reason") in reasons]
    me, states = subjects(token, [html_url(n) for n in personal])
    for notification in personal:
        url = html_url(notification)
        subject = notification.get("subject", {})
        data = {
            "id": notification.get("id"),
            "reason": notification.get("reason"),
            "type": subject.get("type"),
            "repo": notification.get("repository", {}).get("full_name"),
            "unread": notification.get("unread"),
        }
        state = states.get(url)
        if state:
            if moot(data["reason"], state, me):
                log.debug("Skipping moot notification: %s", url)
                continue
            others = [r for r in state["reviewers"] if r != me]
            data.update(state=state["state"], reviewers=others, others_requested=len(others))
        mq.put(url, {
            "title": subject.get("title"),
            "updated": notification.get("updated_at"),
            "notification": data,
        })


def moot(reason, state, me):
    """
    Whether a notification no longer asks anything of me: a review request
    or assignment on a closed issue or PR, or no longer requesting or
    assigning me. NB: A review requested of a team counts as requested.
    """
    if reason == "review_requested":
        return state["state"] != "open" or not (
            me in state["reviewers"] or any("/" in r for r in state["reviewers"])
        )
    if reason == "assign":
        return state["state"] != "open" or me not in state["assignees"]
    return False


_SUBJECT_FIELDS = """
    ... on Issue { state assignees(first: 50) { nodes { login } } }
    ... on PullRequest {
      state
      assignees(first: 50) { nodes { login } }
      reviewRequests(first: 50) {
        nodes { requestedReviewer { ... on User { login } ... on Team { combinedSlug } } }
      }
    }
"""


def subjects(token, urls):
    """
    Look up the issues and PRs at the given URLs, in one GraphQL query.

    :return:
        Tuple of (my login, dict of URL -> {state, assignees, reviewers}),
        where state is "open", "closed" or "merged", and reviewers are the
        requested reviewers' logins, or org/team slugs for teams.
    """
    urls = sorted({u for u in urls if re.search("/(issues|pull)/\\d+$", u)})
    if not urls: return None, {}
    aliases = "\n".join(
        f"  s{i}: resource(url: {json.dumps(u)}) {{{_SUBJECT_FIELDS}}}"
        for i, u in enumerate(urls)
    )
    response = requests.post(
        _GRAPHQL_URL,
        json={"query": f"query {{\n  viewer {{ login }}\n{aliases}\n}}"},
        headers={"User-Agent": "monoqueue", "Authorization": f"bearer {token}"},
        timeout=60,
    )
    response.raise_for_status()
    data = response.json().get("data")
    if not data:
        raise RuntimeError(f"GitHub GraphQL query failed: {response.json().get('errors')}")

    states = {}
    for i, url in enumerate(urls):
        subject = data.get(f"s{i}")
        if not subject or "state" not in subject: continue  # E.g. deleted, or no access.
        reviewers = [
            r.get("login") or r.get("combinedSlug")
            for r in (n.get("requestedReviewer") or {} for n in subject.get("reviewRequests", {}).get("nodes", []))
        ]
        states[url] = {
            "state": subject["state"].lower(),
            "assignees": [a["login"] for a in subject["assignees"]["nodes"]],
            "reviewers": [r for r in reviewers if r],
        }
    return data["viewer"]["login"], states


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
