#!/usr/bin/env python
#
# This is free and unencumbered software released into the public domain.
# See the UNLICENSE file for details.
#
# ------------------------------------------------------------------------
# firefox.py
# ------------------------------------------------------------------------

"""
Routines to extract information from Firefox profiles: bookmarks from the
places.sqlite database, and open tabs, both from this computer's session
store and from other devices' tabs synced via Firefox Sync.
"""

import json
import os
import re
import shlex
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

from . import time
from .log import log


def update(mq, config):
    for bookmark in bookmarks(config["folder"]):
        mq.put(bookmark["url"], {
            "title": bookmark["title"],
            "created": bookmark["dateAdded"],
            "updated": bookmark["lastModified"],
            "bookmark": bookmark
        })


_PROFILE_PARENTS = [
    "~/.mozilla/firefox",
    "~/.mozilla/firefox-esr",
    "~/snap/firefox/common/.mozilla/firefox",
    "~/Library/Application Support/Firefox/Profiles",
]

DEFAULT_SNAPSHOT_DIR = Path("~/.local/share/monoqueue/tabs").expanduser()
DEFAULT_MAX_DEVICE_AGE_DAYS = 30
# NB: Non-interactive ssh sessions often lack ~/bin and ~/.local/bin
# on the PATH, so look for mq there first.
DEFAULT_PULL_COMMAND = (
    "ssh -o BatchMode=yes -o ConnectTimeout=5 {host} "
    "'for mq in ~/bin/mq ~/.local/bin/mq mq; do "
    "command -v $mq >/dev/null && exec $mq snapshot -; done; "
    "echo mq not found >&2; exit 127'"
)


def profile_files(name):
    """
    Find files with the given name across all local Firefox profiles.
    """
    files = []
    for parent in _PROFILE_PARENTS:
        found = list(Path(parent).expanduser().glob(f"*/{name}"))
        for f in found:
            log.debug(f"Found Firefox file: {f}")
        files.extend(found)
    return files


def bookmarks(folder_name=None):
    results = []

    places_dbs = profile_files("places.sqlite")

    if len(places_dbs) == 0:
        log.warning("No Firefox sqlite DBs found!")
        return results

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
                where type = 2 and title = '{folder_name}';
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


def update_tabs(mq, config):
    """
    Add an action item for each open tab, across all devices.

    Tabs come from this computer's Firefox, if any, and from snapshot
    files written by "mq snapshot" on other computers, or pulled from the
    hosts listed in the pull option by running "mq snapshot -" via ssh
    there (see pull_command). For each device,
    the most recently seen data wins. Devices not seen for longer than
    max_device_age_days are skipped, since their tabs are likely gone.
    """
    snapshot_dir = Path(config.get("dir", str(DEFAULT_SNAPSHOT_DIR))).expanduser()
    excludes = [
        re.compile(pattern.strip())
        for pattern in config.get("exclude", "").splitlines()
        if pattern.strip()
    ]
    max_device_age = 86400 * float(config.get("max_device_age_days", DEFAULT_MAX_DEVICE_AGE_DAYS))

    pull_command = config.get("pull_command", DEFAULT_PULL_COMMAND)
    for host in config.get("pull", "").replace(",", " ").split():
        pull(host, pull_command, snapshot_dir)

    snapshots = []
    if config.get("local", "true").lower() != "false":
        snapshots.append(snapshot())
    for path in sorted(snapshot_dir.glob("*.json")):
        try:
            snapshots.append(json.loads(path.read_text()))
        except (OSError, ValueError) as e:
            log.warning("Cannot read tab snapshot %s: %s", path, e)

    # Collect the tabs per URL, across devices.
    tabs = {}
    for device, info in merge_devices(snapshots).items():
        if time.age(info["seen"]).total_seconds() > max_device_age:
            log.debug("Skipping tabs of %s, last seen %s", device, info["seen"])
            continue
        for tab in info["tabs"]:
            url = mq.normalize(tab["url"])
            if any(pattern.search(url) for pattern in excludes): continue
            entry = tabs.setdefault(url, {"title": tab.get("title"), "tabs": []})
            entry["tabs"].append({
                "device": device,
                "last_accessed": tab.get("last_accessed"),
            })

    for url, entry in tabs.items():
        data = {"tabs": entry["tabs"]}
        if entry["title"]: data["title"] = entry["title"]
        mq.put(url, data)


def pull(host, command, snapshot_dir):
    """
    Fetch a tab snapshot from another computer, saving it as
    <snapshot_dir>/<host>.json. On failure (e.g. the computer is off),
    any previous snapshot from that host is kept.
    """
    log.info("Pulling tabs from %s...", host)
    args = shlex.split(command.replace("{host}", host))
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=120, check=False)
    except (OSError, subprocess.TimeoutExpired) as e:
        log.warning("Cannot pull tabs from %s: %s", host, e)
        return
    if result.returncode != 0:
        log.warning("Cannot pull tabs from %s: %s", host, result.stderr.strip())
        return
    try:
        json.loads(result.stdout)
    except ValueError:
        log.warning("Invalid tab snapshot from %s", host)
        return

    snapshot_dir.mkdir(parents=True, exist_ok=True)
    path = snapshot_dir / f"{host}.json"
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(result.stdout)
    os.replace(tmp, path)


def merge_devices(snapshots):
    """
    Combine tab snapshots, keeping the most recently seen tabs per device.
    """
    devices = {}
    for snap in snapshots:
        for device, info in snap.get("devices", {}).items():
            current = devices.get(device)
            if current is None or _newer(info["seen"], current["seen"]):
                devices[device] = info
    return devices


def snapshot():
    """
    Take a snapshot of the open tabs known to this computer's Firefox:
    its own tabs, plus tabs of other devices synced via Firefox Sync.

    Only each tab's URL, title, and last access time are included.

    :return:
        Dict with the snapshot time, host, and tabs per device.
    """
    host = socket.gethostname().split(".")[0]
    devices = {}

    def add(device, seen, tabs):
        current = devices.get(device)
        if current is None:
            devices[device] = {"seen": seen, "tabs": tabs}
        elif device == host:
            # Several local profiles: combine their tabs.
            current["tabs"].extend(tabs)
            current["seen"] = max(current["seen"], seen, key=time.str2dt)
        elif _newer(seen, current["seen"]):
            devices[device] = {"seen": seen, "tabs": tabs}

    for profile in {f.parent for f in profile_files("prefs.js")}:
        local = _session_tabs(profile)
        if local: add(host, *local)
        for device, seen, tabs in _synced_tabs(profile):
            if device != host: add(device, seen, tabs)

    return {"generated": time.string(int(time.now().timestamp())), "host": host, "devices": devices}


def _session_tabs(profile):
    """
    Read open tabs from a profile's session store. While Firefox runs, the
    newest state is in sessionstore-backups/recovery.jsonlz4; after Firefox
    exits cleanly, it is in sessionstore.jsonlz4.

    :return:
        (seen, tabs) tuple, or None if there is no session store.
    """
    candidates = [
        p for p in (
            profile / "sessionstore.jsonlz4",
            profile / "sessionstore-backups" / "recovery.jsonlz4",
        )
        if p.exists()
    ]
    if not candidates: return None
    path = max(candidates, key=lambda p: p.stat().st_mtime)

    try:
        session = _read_jsonlz4(path)
    except (OSError, ValueError) as e:
        log.warning("Cannot read Firefox session %s: %s", path, e)
        return None

    tabs = []
    for window in session.get("windows", []):
        for tab in window.get("tabs", []):
            # Pinned tabs are fixtures (mail, calendar), not action items.
            if tab.get("pinned"): continue
            entries = tab.get("entries", [])
            index = tab.get("index", len(entries))
            if not entries or not 1 <= index <= len(entries): continue
            entry = entries[index - 1]
            if not entry.get("url", "").startswith(("http://", "https://")): continue
            tabs.append({
                "url": entry["url"],
                "title": entry.get("title"),
                "last_accessed": time.string(tab["lastAccessed"] // 1000) if tab.get("lastAccessed") else None,
            })

    return time.string(int(path.stat().st_mtime)), tabs


def _synced_tabs(profile):
    """
    Read other devices' tabs, as synced by Firefox Sync, from a profile.

    :return:
        List of (device, seen, tabs) tuples.
    """
    db = profile / "synced-tabs.db"
    if not db.exists(): return []

    results = []
    with tempfile.TemporaryDirectory() as tmp:
        # NB: Copy to avoid a locked DB in case Firefox is open.
        copy = Path(tmp) / db.name
        shutil.copyfile(db, copy)
        cx = sqlite3.connect(copy)
        try:
            rows = cx.execute("select record, last_modified from tabs").fetchall()
        except sqlite3.Error as e:
            log.warning("Cannot read synced tabs %s: %s", db, e)
            rows = []
        finally:
            cx.close()

    for record, last_modified in rows:
        try:
            data = json.loads(record)
        except ValueError:
            continue
        tabs = []
        for tab in data.get("tabs", []):
            history = tab.get("urlHistory") or []
            if not history or not history[0].startswith(("http://", "https://")): continue
            tabs.append({
                "url": history[0],
                "title": tab.get("title"),
                "last_accessed": time.string(tab["lastUsed"]) if tab.get("lastUsed") else None,
            })
        device = _device_name(data.get("clientName", ""))
        results.append((device, time.string(last_modified // 1000), tabs))
    return results


def _newer(a, b):
    return time.str2dt(a) > time.str2dt(b)


def _device_name(client_name):
    # E.g. "curtis’s Firefox on odo" -> "odo".
    _, on, device = client_name.rpartition(" on ")
    return device if on else client_name


def _read_jsonlz4(path):
    import lz4.block

    data = Path(path).read_bytes()
    if not data.startswith(b"mozLz40\0"):
        raise ValueError("not a mozLz4 file")
    return json.loads(lz4.block.decompress(data[8:]))


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
