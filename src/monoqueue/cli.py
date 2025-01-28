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

import sys
from pprint import pprint

from . import Monoqueue, ui
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

            print(f"[{url}]")

            if metadata: pprint(metadata)
            else: print("<No local metadata>")

            if impact:
                pprint(impact.rules)
                print(f"Impact score: {impact.value}")
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
        print(f"{i:>{w}} [{impact.value}] -- {url} -- {item['title']}")

    return 0


def cmd_ui(*args):
    ui.main(*args)
    return 0


def cmd_up(*args):
    mq = Monoqueue()

    # TODO: Is this too hacky? Think about it.
    mq.progress = lambda more: print(".", flush=True, end="" if more else None)

    mq.update()

    # Persist the updated action items to disk.
    mq.save(metadata_path=None)

    return 0


def main():
    setup_logging()

    usage = """
Usage: mq <command> [<args>]

Valid commands:
  info - show detailed info about action items
    ls - list action items by impact score
    ui - launch the interactive monoqueue user interface
    up - update action item data from linked sources
"""

    args = sys.argv[1:]
    if len(args) == 0:
        sys.stderr.write(usage)
        return 1

    command = args[0]
    args = args[1:]

    if command == "info": return cmd_info(*args)
    if command == "ls": return cmd_ls(*args)
    if command == "ui": return cmd_ui(*args)
    if command == "up": return cmd_up(*args)

    log.error("Invalid subcommand: %s", command)
    sys.stderr.write(usage)
    return 250
