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
    for url in mq.urls():
        if any(arg for arg in args if arg in url):
            info = mq.info(url)
            print(f"[{url}]")
            pprint(info)
            print()

    return 0


def cmd_ls(*args):
    html = "--html" in args

    if html:
        raise RuntimeError("HTML export is not implemented yet")

    mq = Monoqueue()
    mq.load()
    urls = mq.urls()

    for i, url in enumerate(urls):
        if i > 10: break
        info = mq.info(url)
        impact = mq.impact(url)
        print(f"[{impact}] -- {url} -- {info['title']}")

    return 0


def cmd_ui(*args):
    ui.main()
    return 0


def cmd_up(*args):
    mq = Monoqueue()
    # TODO: Is this too hacky? Think about it.
    mq.progress = lambda more: print(".", flush=True, end="" if more else None)
    mq.update()
    mq.save()
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
    elif command == "ls": return cmd_ls(*args)
    elif command == "ui": return cmd_ui(*args)
    elif command == "up": return cmd_up(*args)
    else:
        log.error("Invalid subcommand: %s", command)
        sys.stderr.write(usage)
        return 250

    return 0
