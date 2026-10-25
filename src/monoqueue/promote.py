#!/usr/bin/env python
#
# This is free and unencumbered software released into the public domain.
# See the UNLICENSE file for details.
#
# ------------------------------------------------------------------------
# promote.py
# ------------------------------------------------------------------------

"""
Routines to promote an action item (e.g. a browser tab, forum topic, or
task) to a public GitHub issue, so that the work is tracked visibly.

The promoted item is then linked into the new issue: they remain one
action item, at the issue's URL, which also carries the original's data
(tabs, due date, etc.). Configure via a [promote] section of settings.conf,
which may also override the [agent] settings for drafting:

    [promote]
    repo = me/tasks               # The fallback repository for new issues.
"""

import os
import re
import subprocess
import tempfile
from typing import Any, Dict, List, Optional

from . import agent
from .log import log


def candidate_repos(mq, url: str, config: Dict[str, str] = None) -> List[str]:
    """
    Get the repositories where an issue promoted from the given action item
    might belong, most likely first: the item's own repository, those of
    GitHub links within the item, and finally the configured fallback, if any.
    """
    config = config or {}
    item = mq.item(url) or {}
    urls = [url]
    urls += (item.get("task") or {}).get("links", [])
    urls += mq.metadata(url).get("links", [])
    text = (item.get("issue") or {}).get("body") or item.get("description") or ""
    urls += re.findall("https://github\\.com/[^\\s)\\]>\"']+", text)

    repos = []
    for u in urls:
        repo = agent.github_repo(u)
        if repo and repo not in repos: repos.append(repo)
    fallback = config.get("repo")
    if fallback and fallback not in repos: repos.append(fallback)
    return repos


def check_promotable(mq, url: str) -> None:
    """
    Raise ValueError if the given action item cannot be promoted.
    """
    if url.startswith("monoqueue:"):
        raise ValueError("Alerts cannot be promoted")
    if re.match("https://github\\.com/[^/]+/[^/]+/(issues|pull)/\\d+", url):
        raise ValueError("Already a GitHub issue")


def draft(mq, url: str, why: str = "", config: Dict[str, str] = None) -> Dict[str, Any]:
    """
    Draft an issue for the given action item, via an agent.
    """
    check_promotable(mq, url)
    if why:
        mq.metadata(url)["note"] = why
        mq.mark_dirty(url)
    repos = candidate_repos(mq, url, config)
    if not repos:
        raise ValueError("No repository for the issue: configure one via [promote] repo")
    issue = agent.draft_issue(mq, url, repos, why, config)
    # NB: The body must link the original, whatever the agent wrote.
    if url not in issue["body"]: issue["body"] += f"\n\nSee: {url}"
    return issue


def create(mq, url: str, issue: Dict[str, Any]) -> str:
    """
    Create the given (drafted) issue on GitHub, and link the action item
    into it.

    :return:
        The new issue's URL.
    """
    log.info("Creating issue in %s: %s", issue["repo"], issue["title"])
    result = subprocess.run(
        ["gh", "issue", "create", "--repo", issue["repo"],
         "--title", issue["title"], "--body-file", "-"],
        input=issue["body"], capture_output=True, text=True, check=False, timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Cannot create issue: {result.stderr.strip()}")
    issue_url = mq.link(url, result.stdout.strip().splitlines()[-1])
    # Until the GitHub source fetches the issue, title the item after it.
    item = mq.item(issue_url)
    if item is not None and "issue" not in item: item["title"] = issue["title"]
    return issue_url


def interact(mq, url: str, why: str = "", repo: Optional[str] = None,
             yes: bool = False) -> Optional[str]:
    """
    Promote an action item on the terminal: draft an issue, show it, and
    let the user edit it, before creating it only if they confirm.

    :return:
        The new issue's URL, or None if the user declined.
    """
    url = mq.normalize(url)
    print(f"Drafting an issue for {url}...", flush=True)
    issue = draft(mq, url, why, mq.config.action("promote"))
    if repo: issue["repo"] = repo

    while not yes:
        print()
        print(format_draft(issue))
        answer = input(f"Create this issue in {issue['repo']}? [y]es, [e]dit, [N]o: ").strip().lower()
        if answer == "e": issue = edit(issue)
        elif answer == "y": break
        else: return None

    issue_url = create(mq, url, issue)
    print(f"Created {issue_url}")
    return issue_url


def edit(issue: Dict[str, Any]) -> Dict[str, Any]:
    """
    Edit a drafted issue in the user's editor.
    """
    with tempfile.NamedTemporaryFile("w+", suffix=".md", prefix="issue-") as f:
        f.write(format_draft(issue))
        f.flush()
        editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi"
        subprocess.run([editor, f.name], check=False)
        f.seek(0)
        return parse_draft(f.read())


def format_draft(issue: Dict[str, Any]) -> str:
    """
    Format a drafted issue as editable text: repo and title lines, then
    a blank line, then the body.
    """
    return f"repo: {issue['repo']}\ntitle: {issue['title']}\n\n{issue['body']}\n"


def parse_draft(text: str) -> Dict[str, Any]:
    """
    Parse text in the format of format_draft, e.g. after editing it.
    """
    header, _, body = text.partition("\n\n")
    issue = {"body": body.strip()}
    for line in header.splitlines():
        key, _, value = line.partition(":")
        if key.strip() in ("repo", "title"): issue[key.strip()] = value.strip()
    if not issue.get("repo") or not issue.get("title"):
        raise ValueError("The draft needs repo: and title: lines")
    return issue
