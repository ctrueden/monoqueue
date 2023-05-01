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

import os, shutil, sqlite3, sys, tempfile
from pathlib import Path

from . import time


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
    firefox_config_dir = Path("~/.mozilla/firefox").expanduser()
    places_dbs = list(firefox_config_dir.glob("*/places.sqlite"))

    results = []

    if len(places_dbs) > 0:
        tf = tempfile.NamedTemporaryFile(delete=False, prefix="firefox", suffix=".sqlite")
        temp_db_path = tf.name
        tf.close()

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

        # TODO: recently deleted bookmarks are still on the list, even after quitting Firefox?
        # Test this more, and/or read. What is the separate recently deleted bookmarks table for?

        for title, url, date_added, last_modified in items:
            results.append({
                "title": title,
                "url": url,
                "dateAdded": time.string(date_added // 1000000),
                "lastModified": time.string(last_modified // 1000000),
            })

        cx.close()

    os.remove(temp_db_path)

    return results


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
