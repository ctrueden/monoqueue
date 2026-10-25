#!/usr/bin/env python
#
# This is free and unencumbered software released into the public domain.
# See the UNLICENSE file for details.
#
# ------------------------------------------------------------------------
# cli.py
# ------------------------------------------------------------------------

"""
The monoqueue command line tool.
"""

import subprocess
import sys
from pprint import pprint

from . import Monoqueue, agent, config, promote, ui
from .lock import lock
from .log import log, setup_logging


def cmd_info(*args):
    if len(args) == 0:
        log.error("Please specify at least one term to match.")
        return 3

    mq = Monoqueue()
    mq.load()
    for url in mq.urls(active_only=False):
        if any(arg for arg in args if arg in url):
            metadata = mq.metadata(url)
            impact = mq.impact(url)
            item = mq.item(url)

            urls = mq.urls()
            rank = f"{urls.index(url) + 1} of {len(urls)}" if url in urls else "inactive"
            print(f"[{url}] (rank {rank})")

            if metadata: pprint(metadata)
            else: print("<No local metadata>")

            if impact:
                pprint(impact.rules)
                print(f"Impact score: {impact.value:.1f}")
            else:
                print("<No computed impact>")

            if item: pprint(item)
            else: print("<No action item data>")

    return 0


def cmd_ls(*args):
    html = "--html" in args

    if html:
        raise RuntimeError("HTML export is not implemented yet")

    mq = Monoqueue()
    mq.load()
    urls = mq.urls()

    def inlo(fragment, string):
        return fragment.lower() in string.lower()

    def contains(url, item, arg):
        if inlo(arg, url) or inlo(arg, item['title']): return True
        return (
            'issue' in item
            and item['issue'] is not None
            and 'body' in item['issue']
            and item['issue']['body'] is not None
            and inlo(arg, item['issue']['body'])
        )

    w = len(str(len(urls)))
    for i, url in enumerate(urls):
        item = mq.item(url)

        # Filter out non-matching items.
        if any(not contains(url, item, arg) for arg in args): continue

        impact = mq.impact(url)
        print(f"{i + 1:>{w}} [{impact.value:.1f}] -- {url} -- {item['title']}")

    return 0


def cmd_triage(*args):
    if len(args) == 0:
        log.error("Please specify the URLs of action items to triage.")
        return 3

    mq = Monoqueue()
    mq.load()
    for url in args:
        url = mq.normalize(url)
        if mq.item(url) is None: log.warning("Not in the queue: %s", url)
        log.info("Triaging %s...", url)
        try:
            result = agent.triage(mq, url, mq.config.action("triage"))
        except Exception as e:
            log.error("Cannot triage %s: %s", url, e)
            continue
        print(f"{url}\n  {result['size']}, {result['actor']}: {result['next_action']}\n  {result['summary']}")
        mq.save(items_path=None)
    return 0


def cmd_promote(*args):
    args = list(args)
    options = {}
    for flag in ("--repo", "--why"):
        if flag in args:
            i = args.index(flag)
            options[flag] = args[i + 1]
            del args[i:i + 2]
    yes = "--yes" in args
    if yes: args.remove("--yes")
    if len(args) != 1:
        log.error("Usage: mq promote <url> [--repo owner/name] [--why text] [--yes]")
        return 3

    mq = Monoqueue()
    mq.load()
    issue_url = promote.interact(mq, args[0], options.get("--why", ""),
                                 options.get("--repo"), yes)
    mq.save(items_path=None)
    return 0 if issue_url else 1


def cmd_link(*args):
    if len(args) != 2:
        log.error("Usage: mq link <url> <target-url>")
        return 3

    mq = Monoqueue()
    mq.load()
    print(mq.link(args[0], args[1]))
    mq.save(items_path=None)
    return 0


def cmd_tune(*args):
    args = list(args)
    edit = "--edit" in args
    if edit: args.remove("--edit")
    if len(args) != 1:
        log.error("Usage: mq tune <url> [--edit]")
        return 3

    mq = Monoqueue()
    mq.load()
    url = mq.normalize(args[0])
    command, cwd = agent.tune_command(mq, url, mq.config.action("tune"))
    if edit: command = agent.edit_first(command)
    return subprocess.run(command, cwd=cwd, check=False).returncode


def cmd_migrate_config(*args):
    sources_dir = Monoqueue._DEFAULT_SOURCES_DIR
    config.migrate(sources_dir=sources_dir)
    print(f"Split {config.LEGACY_PATH} into {config.CONFIG_DIR}/{{rules,sources,settings}}.conf.")
    for old, new in config.RENAMED.items():
        print(f"Renamed source [{old}] to [{new}], if present.")
    print(f"Once all is well, delete {config.LEGACY_PATH}, which holds secrets.")
    return 0


def cmd_ui(*args):
    ui.main(*args)
    return 0


DEFAULT_UP_WAIT = 600  # 10 minutes


def cmd_up(*args):
    args = list(args)
    wait = DEFAULT_UP_WAIT
    if "--wait" in args:
        i = args.index("--wait")
        wait = float(args[i + 1])
        del args[i:i + 2]

    mq = Monoqueue()

    # TODO: Is this too hacky? Think about it.
    mq.progress = lambda more: print(".", flush=True, end="" if more else None)

    # Only one update at a time: e.g. a quick "mq up tabs" from cron
    # could otherwise overlap a long full update.
    lock_path = Monoqueue._DEFAULT_ITEMS_PATH.parent / "up.lock"
    try:
        with lock(lock_path, timeout=wait):
            mq.update(args or None)

            # Persist the updated action items to disk.
            mq.save(metadata_path=None)

            # Summarize, taking deferrals into account.
            mq.load(items_path=None)
            mq.save_status()
    except TimeoutError:
        log.error("Another update is still running after %g seconds; giving up.", wait)
        return 75  # EX_TEMPFAIL

    return 0


def main():
    setup_logging()

    usage = """
Usage: mq <command> [<args>]

Valid commands:
          info - show detailed info about action items
          link - link an action item into another (e.g. a tab into an issue)
            ls - list action items by impact score
migrate-config - split ~/.config/monoqueue.conf into ~/.config/monoqueue/*.conf
       promote - create a GitHub issue for an action item, and link it in
        triage - have an agent estimate action items' size and next action
          tune - adjust the rules with an agent, from a misprioritized item
            ui - launch the interactive monoqueue user interface
            up - update action item data from linked sources (all, or those given);
                 waits up to 600 seconds for another update to finish (--wait N)
"""

    args = sys.argv[1:]
    if len(args) == 0:
        sys.stderr.write(usage)
        return 1

    command = args[0]
    args = args[1:]

    if command == "info": return cmd_info(*args)
    if command == "link": return cmd_link(*args)
    if command == "ls": return cmd_ls(*args)
    if command == "migrate-config": return cmd_migrate_config(*args)
    if command == "promote": return cmd_promote(*args)
    if command == "triage": return cmd_triage(*args)
    if command == "tune": return cmd_tune(*args)
    if command == "ui": return cmd_ui(*args)
    if command == "up": return cmd_up(*args)

    log.error("Invalid subcommand: %s", command)
    sys.stderr.write(usage)
    return 250
