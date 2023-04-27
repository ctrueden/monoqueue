#!/usr/bin/env python
#
# This is free and unencumbered software released into the public domain.
# See the UNLICENSE file for details.
#
# ------------------------------------------------------------------------
# firefox.py
# ------------------------------------------------------------------------

"""
Routines to extract information from Firefox's places.sqlite database.
"""

import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path


def update(mq, config):
    for bookmark in bookmarks(config["folder"]):
        url = bookmark["url"]
        if not url in mq.data:
            mq.data[url] = {}

        mq.data[url].update({
            "title": bookmark["title"],
            "created": bookmark["dateAdded"],
            "updated": bookmark["lastModified"],
            "bookmark": bookmark
        })


def bookmarks(folder_name=None):
    temp_db_path = "tmp.places.sqlite" # FIXME: use Python API to make a suitable temp file

    firefox_config_dir = Path("~/.mozilla/firefox").expanduser()
    places_dbs = list(firefox_config_dir.glob("*/places.sqlite"))

    results = []

    for db in places_dbs:
        # NB: make a copy to avoid locked DB in case Firefox is open.
        shutil.copyfile(db, temp_db_path)

        cx = sqlite3.connect(temp_db_path)

        folder_clause = ""
        if folder_name is not None:
            folder_ids = cx.execute(f"""
                select id from moz_bookmarks
                where type = 2 and title = \"{folder_name}\";
                """)

            ids = ", ".join(str(folder_id) for folder_id, in folder_ids)
            if len(ids) == 0:
                continue

            folder_clause = f"and b.parent in ({ids})"

        items = cx.execute(f"""
            select b.title, h.url, b.dateAdded, b.lastModified
            from moz_bookmarks b, moz_places h
            where b.fk = h.id
            {folder_clause};
            """)

        # FIXME: recently deleted bookmarks are still on the list, even after quitting Firefox?
        # Test this more, and/or read. What is the separate recently deleted bookmarks table for?

        for title, url, date_added, last_modified in items:
            results.append({
                "title": title,
                "url": url,
                "dateAdded": _ts2dt2s(date_added),
                "lastModified": _ts2dt2s(last_modified),
            })

        cx.close()

    os.remove(temp_db_path)

    return results


def _ts2dt2s(v):
    """Timestamp -> datetime -> string."""
    dt = datetime.fromtimestamp(v / 1000000)
    s = dt.isoformat()
    plus = s.find("+")
    if plus >= 0: s = s[:plus]
    return s + "Z"


def main(*args):
    results = bookmarks("ACTION")
    for item in results:
        title = item["title"]
        url = item["url"]
        date_added = item["dateAdded"]
        date_modified = item["lastModified"]
        print(f"[{title}]({url}) -- {date_added} -> {date_modified}")


if __name__ == "__main__":
    main(*sys.argv[1:])
