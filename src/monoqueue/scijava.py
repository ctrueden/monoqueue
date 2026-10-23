#!/usr/bin/env python
#
# This is free and unencumbered software released into the public domain.
# See the UNLICENSE file for details.
#
# ------------------------------------------------------------------------
# scijava.py
# ------------------------------------------------------------------------

"""
Routines to download community obligations from the SciJava team portal.

The portal at https://status.scijava.org/team publishes, per developer,
the GitHub items and releases they are responsible for, by role:

* reviewer_prs: open PRs on components they review
* support_issues: open issues on components they support
* debugger_bugs: open bugs on components they debug
* developer_features: open enhancements on components they develop
* maintainer_releases: components they maintain needing a release

Each action item gets a scijava/roles list naming the roles it came from,
for use in rules such as:

    "reviewer_prs" in scijava/roles -> +10: SciJava PR review
"""

import requests

from . import time
from .log import log

DEFAULT_URL = "https://status.scijava.org/team.json"
DEFAULT_INCLUDE = "reviewer_prs, maintainer_releases"
DEFAULT_MAX_AGE_DAYS = 2

ROLES = (
    "reviewer_prs",
    "support_issues",
    "debugger_bugs",
    "developer_features",
    "maintainer_releases",
)

STATUS_WORKFLOW_URL = "https://github.com/scijava/pom-scijava/actions/workflows/status.yml"


def update(mq, config):
    url = config.get("url", DEFAULT_URL)
    dev_id = config["dev_id"]
    include = {
        role.strip()
        for role in config.get("include", DEFAULT_INCLUDE).split(",")
    }
    max_age_days = float(config.get("max_age_days", DEFAULT_MAX_AGE_DAYS))

    response = requests.get(url, headers={"User-Agent": "monoqueue"}, timeout=30)
    response.raise_for_status()
    team = response.json()

    _check_staleness(mq, team.get("generated"), max_age_days)

    rows = [row for row in team.get("rows", []) if row.get("dev_id") == dev_id]
    if not rows:
        log.warning("No SciJava team row for developer %s", dev_id)
        return

    for item_url, info in collect(rows[0]).items():
        # Roles not included only annotate items found by other sources,
        # so that e.g. 1000+ support issues do not flood the queue.
        if not include & set(info["roles"]) and mq.normalize(item_url) not in mq.items:
            continue
        data = {"scijava": info}
        if info.get("title"): data["title"] = info["title"]
        mq.put(item_url, data)


def collect(row):
    """
    Gather a team.json developer row into a dict of info per URL.

    :param row:
        The developer row from team.json.
    :return:
        Dict mapping each URL to its roles, title, and (for releases)
        the Maven groupId:artifactId of each component needing release.
    """
    items = {}
    popups = row.get("popups", {})
    for role in ROLES:
        for entry in popups.get(role, []):
            info = items.setdefault(entry["url"], {"roles": []})
            if role not in info["roles"]: info["roles"].append(role)
            if "title" in entry:
                info["title"] = entry["title"]
            if "ga" in entry:
                info.setdefault("components", []).append(entry["ga"])

    # Releases have no title of their own; describe what needs releasing.
    for info in items.values():
        components = info.get("components")
        if components and "title" not in info:
            info["title"] = (
                f"Release {components[0]}" if len(components) == 1
                else f"Release {len(components)} components: {', '.join(components)}"
            )

    return items


def _check_staleness(mq, generated, max_age_days):
    if not generated:
        log.warning("SciJava team data has no generation timestamp")
        return
    age = time.age(generated)
    if age.total_seconds() <= max_age_days * 86400: return

    # Stale data means the status job is probably broken; make it an item.
    log.warning("SciJava team data is %d days old", age.days)
    mq.put(STATUS_WORKFLOW_URL, {
        "title": f"Fix status.scijava.org: team data is {age.days} days stale",
        "created": time.string(time.str2dt(generated)),
        "updated": time.string(time.str2dt(generated)),
        "scijava": {"roles": ["stale_status"]},
    })
