#!/usr/bin/env python
#
# This is free and unencumbered software released into the public domain.
# See the UNLICENSE file for details.
#
# ------------------------------------------------------------------------
# agent.py
# ------------------------------------------------------------------------

"""
Routines to hand action items to an AI agent (Claude Code, by default):
to triage them, estimating their size and next action; to draft GitHub
issues promoting them; and to work on them interactively.

Configure via an [agent] section:

    [agent]
    command = claude              # The agent CLI.
    args = --verbose              # Extra arguments, for interactive work only.
    model = sonnet                # The model for triage and drafting.
    code_dir = ~/code             # Where clones of GitHub repos live.
    about = I maintain ...        # About you, to give agents context.

Triage results are stored in the item's metadata, where rules can see
them, e.g.:

    meta/triage/size in ("XS", "S")      -> +5: quick win
    meta/triage/actor == "others"        -> /4: waiting on others
"""

import json
import re
import shlex
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import time
from .log import log

DEFAULT_COMMAND = "claude"
DEFAULT_MODEL = "sonnet"
DEFAULT_CODE_DIR = "~/code"
DEFAULT_TIMEOUT = 600

# Read-only tools an agent may use while triaging or drafting, to look
# more closely at an item, e.g. at an issue's comments or a PR's diff.
READ_ONLY_TOOLS = [
    "Bash(gh issue view:*)",
    "Bash(gh pr view:*)",
    "Bash(gh pr diff:*)",
    "Bash(gh repo view:*)",
    "WebFetch",
]

SIZES = {
    "XS": "under 15 minutes",
    "S": "under an hour",
    "M": "a few hours",
    "L": "a day or two",
    "XL": "more than two days, best split up",
}

TRIAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "What the item is about, in one sentence."},
        "size": {"type": "string", "enum": list(SIZES)},
        "next_action": {"type": "string", "description": "The concrete next step, as an imperative sentence."},
        "actor": {
            "type": "string",
            "enum": ["me", "agent", "others"],
            "description": "Who must take the next action: me personally, an AI agent "
                           "(perhaps with my review), or someone else (I am waiting on them).",
        },
    },
    "required": ["summary", "size", "next_action", "actor"],
}

ISSUE_SCHEMA = {
    "type": "object",
    "properties": {
        "repo": {"type": "string", "description": "The owner/name of the GitHub repository."},
        "title": {"type": "string"},
        "body": {"type": "string", "description": "The issue body, in GitHub Markdown."},
    },
    "required": ["repo", "title", "body"],
}

DEFAULT_ABOUT = (
    "I use monoqueue to prioritize my action items, which come from "
    "GitHub, forums, browser tabs, tasks, and more."
)


def describe(mq, url: str, max_body: int = 4000) -> str:
    """
    Describe an action item in plain text, for an agent's prompt.
    """
    item = mq.item(url) or {}
    lines = [f"URL: {url}", f"Title: {(item.get('title') or '').strip()}"]
    if item.get("sources"): lines.append(f"Sources: {', '.join(item['sources'])}")
    for key in ("created", "updated", "due"):
        if item.get(key): lines.append(f"{key.capitalize()}: {item[key]}")

    issue = item.get("issue")
    if issue:
        kind = "pull request" if issue.get("pull_request") else "issue"
        lines.append(f"GitHub {kind} #{issue.get('number')}, {issue.get('state')}"
                     f"{' (draft)' if issue.get('draft') else ''}, "
                     f"by {(issue.get('user') or {}).get('login')} ({issue.get('author_association')}), "
                     f"{issue.get('comments')} comments")
        labels = [label.get("name") for label in issue.get("labels") or []]
        if labels: lines.append(f"Labels: {', '.join(labels)}")
        assignees = [a.get("login") for a in issue.get("assignees") or []]
        if assignees: lines.append(f"Assignees: {', '.join(assignees)}")
        if issue.get("milestone"): lines.append(f"Milestone: {issue['milestone'].get('title')}")
    topic = item.get("topic")
    if topic:
        lines.append(f"Forum topic with {topic.get('posts_count')} posts, tags: "
                     f"{', '.join(topic.get('tags') or [])}; "
                     f"{'has' if topic.get('has_accepted_answer') else 'no'} accepted answer")
    if item.get("notification"):
        lines.append(f"Unread GitHub notification: {item['notification'].get('reason')}")
    if item.get("scijava"):
        lines.append(f"My SciJava team roles for it: {', '.join(item['scijava'].get('roles', []))}")
    if item.get("tabs"):
        devices = sorted({t.get("device") for t in item["tabs"]})
        lines.append(f"Open in my browser tabs on: {', '.join(devices)}")
    if item.get("task"):
        task = item["task"]
        lines.append(f"A task in my task list {task.get('list')!r}, priority {task.get('priority')}")
        if task.get("links"): lines.append(f"Task links: {', '.join(task['links'])}")
    if item.get("bookmark"):
        lines.append("Bookmarked in my browser's action folder")

    links = mq.metadata(url).get("links")
    if links: lines.append(f"Linked items: {', '.join(links)}")
    note = mq.metadata(url).get("note")
    if note: lines.append(f"My note: {note}")

    body = (issue or {}).get("body") or item.get("description")
    if body:
        if len(body) > max_body: body = body[:max_body] + "\n[...truncated]"
        lines += ["", "Body:", body]
    return "\n".join(lines)


def triage(mq, url: str, config: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """
    Ask an agent to estimate an action item's size and next action,
    and record the result in the item's metadata.
    """
    config = config or {}
    prompt = f"""{config.get("about", DEFAULT_ABOUT)}

Triage this action item for me: summarize it, estimate the size of the
work it needs from here, and name the concrete next action and who must
take it. If useful, look more closely at the item first (e.g. read the
issue's comments with gh), but do not change anything.

Sizes: {"; ".join(f"{k} = {v}" for k, v in SIZES.items())}.

{describe(mq, url)}
"""
    result = run(prompt, TRIAGE_SCHEMA, config)
    result["at"] = time.string(time.now())
    mq.metadata(url)["triage"] = result
    mq.mark_dirty(url)
    return result


def draft_issue(mq, url: str, repos: List[str], why: str = "",
                config: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """
    Ask an agent to draft a GitHub issue tracking an action item.

    :param repos:
        Candidate repositories, most likely first.
    :param why:
        Why I care about the item, to include in the issue.
    """
    config = config or {}
    prompt = f"""{config.get("about", DEFAULT_ABOUT)}

Draft a public GitHub issue that tracks this action item, so that my
colleagues can see I intend to work on it. Write it concisely, as I would:
state the problem or goal, link the original item, and include what I said
about why it matters, if anything. Do not invent details; if useful, look
more closely at the item first, but do not create or change anything.

Choose the repository from these candidates, most likely first, unless
the item clearly belongs elsewhere: {", ".join(repos)}.

Why I care: {why or "(not given)"}

{describe(mq, url)}
"""
    return run(prompt, ISSUE_SCHEMA, config)


def run(prompt: str, schema: Dict[str, Any], config: Dict[str, str]) -> Dict[str, Any]:
    """
    Run an agent non-interactively, with read-only tools, returning its
    structured output, which conforms to the given JSON schema.
    """
    args = command(config) + [
        "-p", prompt,
        "--model", config.get("model", DEFAULT_MODEL),
        "--output-format", "json",
        "--json-schema", json.dumps(schema),
        "--allowedTools", *READ_ONLY_TOOLS,
    ]
    log.debug("Running agent: %s", args[0])
    # NB: Run outside any project, so that no project's instructions apply.
    with tempfile.TemporaryDirectory(prefix="monoqueue-agent-") as cwd:
        result = subprocess.run(
            args, cwd=cwd, capture_output=True, text=True, check=False,
            timeout=float(config.get("timeout", DEFAULT_TIMEOUT)),
        )
    try:
        output = json.loads(result.stdout)
    except ValueError:
        raise RuntimeError(f"Agent failed: {result.stderr.strip() or result.stdout.strip()}")
    if output.get("is_error") or not output.get("structured_output"):
        raise RuntimeError(f"Agent failed: {output.get('result') or output.get('subtype')}")
    log.debug("Agent cost: $%s", output.get("total_cost_usd"))
    return output["structured_output"]


def work_command(mq, url: str, config: Optional[Dict[str, str]] = None):
    """
    Get the command line and working directory for working on an action
    item interactively with an agent: in the local clone of the item's
    GitHub repository, if there is one.

    :return:
        Tuple of (args, cwd).
    """
    config = config or {}
    cwd = None
    repo = github_repo(url)
    if repo:
        clone = Path(config.get("code_dir", DEFAULT_CODE_DIR)).expanduser() / repo
        if clone.is_dir(): cwd = clone

    prompt = f"""{config.get("about", DEFAULT_ABOUT)}

Help me with this action item from my queue. Look into it first (e.g.
with gh), then tell me what you found and propose a plan before you
change anything, or post anything publicly.

{describe(mq, url)}
"""
    next_action = (mq.metadata(url).get("triage") or {}).get("next_action")
    if next_action:
        prompt += f"\nTriage suggested this next action: {next_action}\n"
    if repo and not cwd:
        prompt += f"\nIf you need the code, clone {repo} into {config.get('code_dir', DEFAULT_CODE_DIR)}/{repo}.\n"
    args = command(config) + shlex.split(config.get("args", "")) + [prompt]
    return args, cwd


def command(config: Dict[str, str]) -> List[str]:
    """
    Get the agent command, split into arguments (e.g. for a wrapper script
    taking arguments of its own).
    """
    return shlex.split(config.get("command", DEFAULT_COMMAND))


def github_repo(url: str) -> Optional[str]:
    """
    Get the owner/name of the GitHub repository a URL is within, if any.
    """
    m = re.match("https://github\\.com/([\\w.-]+)/([\\w.-]+)", url)
    if not m or m.group(1) in ("orgs", "settings", "notifications", "users"): return None
    return f"{m.group(1)}/{m.group(2).removesuffix('.git')}"
