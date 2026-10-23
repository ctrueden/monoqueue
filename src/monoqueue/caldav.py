#!/usr/bin/env python
#
# This is free and unencumbered software released into the public domain.
# See the UNLICENSE file for details.
#
# ------------------------------------------------------------------------
# caldav.py
# ------------------------------------------------------------------------

"""
Routines to download tasks (VTODO items) from a CalDAV server, such as
Nextcloud, Fastmail, iCloud, or Radicale.

Each open task becomes an action item, with fields for use in rules:

    due -> due date, also as seconds_until_due (negative if overdue)
    task/priority -> 1 (highest) to 9 (lowest), or 0 if undefined
    task/list -> name of the task list
    task/categories -> list of tags
    task/links -> URLs from the task's URL field and description
"""

import datetime
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urljoin

import icalendar
import requests

from . import time
from .log import log

_NS = {"d": "DAV:", "c": "urn:ietf:params:xml:ns:caldav"}

_PROPFIND_PRINCIPAL = """<?xml version="1.0"?>
<d:propfind xmlns:d="DAV:"><d:prop><d:current-user-principal/></d:prop></d:propfind>"""

_PROPFIND_HOME = """<?xml version="1.0"?>
<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
  <d:prop><c:calendar-home-set/></d:prop>
</d:propfind>"""

_PROPFIND_CALENDARS = """<?xml version="1.0"?>
<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
  <d:prop>
    <d:displayname/>
    <d:resourcetype/>
    <c:supported-calendar-component-set/>
  </d:prop>
</d:propfind>"""

_REPORT_TODOS = """<?xml version="1.0"?>
<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
  <d:prop><c:calendar-data/></d:prop>
  <c:filter>
    <c:comp-filter name="VCALENDAR"><c:comp-filter name="VTODO"/></c:comp-filter>
  </c:filter>
</c:calendar-query>"""

_URL_PATTERN = re.compile("https?://[^\\s<>\"')\\]]+")


def update(mq, config):
    client = CalDAV(
        url=config["url"],
        username=config.get("username"),
        password=config.get("password"),
        verify=_verify(config.get("verify", "true")),
    )
    lists = {
        name.strip()
        for name in config.get("lists", "").split(",")
        if name.strip()
    }
    link = config.get("link")

    for calendar in client.task_lists():
        if lists and calendar["name"] not in lists: continue
        log.debug("Reading task list %s", calendar["name"])
        for href, data in client.todos(calendar["url"]):
            for task in parse_todos(data):
                if task["status"] in ("COMPLETED", "CANCELLED"): continue
                task["list"] = calendar["name"]
                task_url = urljoin(calendar["url"], href)
                url = (
                    link.format(
                        calendar=calendar["url"].rstrip("/").rsplit("/", 1)[-1],
                        task=href.rstrip("/").rsplit("/", 1)[-1],
                        uid=task["uid"],
                    )
                    if link else task_url
                )
                mq.put(url, {
                    "title": task["summary"],
                    "created": task["created"],
                    "updated": task["updated"],
                    "description": task["description"],
                    "due": task["due"],
                    "task": task,
                })


def parse_todos(data):
    """
    Parse the VTODO components of an iCalendar document.

    :param data:
        iCalendar text, as returned by a CalDAV server.
    :return:
        List of dicts describing each task.
    """
    tasks = []
    for todo in icalendar.Calendar.from_ical(data).walk("VTODO"):
        # A recurring task has one VTODO per overridden occurrence;
        # just use the master.
        if todo.get("RECURRENCE-ID") is not None: continue

        description = str(todo.get("DESCRIPTION", ""))
        links = []
        if todo.get("URL"): links.append(str(todo.get("URL")))
        for link in _URL_PATTERN.findall(description):
            # A URL ending a sentence should not include its punctuation.
            link = link.rstrip(".,;:!?")
            if link not in links: links.append(link)

        categories = []
        cats = todo.get("CATEGORIES")
        for cat in (cats if isinstance(cats, list) else [cats] if cats else []):
            categories.extend(str(c) for c in cat.cats)

        tasks.append({
            "uid": str(todo.get("UID", "")),
            "summary": str(todo.get("SUMMARY", "")),
            "description": description,
            "status": str(todo.get("STATUS", "NEEDS-ACTION")).upper(),
            "priority": int(todo.get("PRIORITY", 0)),
            "percent_complete": int(todo.get("PERCENT-COMPLETE", 0)),
            "categories": categories,
            "links": links,
            "due": _timestamp(todo, "DUE"),
            "start": _timestamp(todo, "DTSTART"),
            "created": _timestamp(todo, "CREATED") or _timestamp(todo, "DTSTAMP"),
            "updated": _timestamp(todo, "LAST-MODIFIED") or _timestamp(todo, "DTSTAMP"),
        })
    return tasks


def _timestamp(component, name):
    prop = component.get(name)
    if prop is None: return None
    value = prop.dt
    if not isinstance(value, datetime.datetime):
        # An all-day date: due by the end of that day.
        value = datetime.datetime.combine(value, datetime.time(23, 59, 59))
    # NB: Floating (naive) times are taken to be UTC.
    return time.string(value)


def _verify(value):
    if value.lower() in ("false", "no", "off", "0"): return False
    if value.lower() in ("true", "yes", "on", "1"): return True
    if Path(value).expanduser().exists():
        return str(Path(value).expanduser())  # A CA bundle or directory.
    raise ValueError(
        f"verify must be true, false, or the path of a CA bundle or directory, not: {value!r}"
    )


class CalDAV:
    """
    A minimal CalDAV client: just enough to read task lists.
    """

    def __init__(self, url, username=None, password=None, verify=True):
        self._url = url if url.endswith("/") else url + "/"
        self._session = requests.Session()
        self._session.headers["User-Agent"] = "monoqueue"
        if username: self._session.auth = (username, password)
        self._session.verify = verify
        if verify is False:
            # Skipping verification was explicitly configured; don't nag.
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def task_lists(self):
        """
        Get the calendars that can hold tasks.

        :return:
            List of dicts with name and (absolute) url of each task list.
        """
        principal = self._href(self._url, _PROPFIND_PRINCIPAL, "d:current-user-principal")
        home = self._href(principal, _PROPFIND_HOME, "c:calendar-home-set")

        lists = []
        for response in self._request("PROPFIND", home, _PROPFIND_CALENDARS, depth=1):
            prop = response.find("d:propstat/d:prop", _NS)
            if prop is None or prop.find("d:resourcetype/c:calendar", _NS) is None: continue
            components = {
                comp.get("name")
                for comp in prop.findall("c:supported-calendar-component-set/c:comp", _NS)
            }
            # NB: No component set means all components are supported.
            if components and "VTODO" not in components: continue
            href = urljoin(home, response.findtext("d:href", namespaces=_NS))
            name = prop.findtext("d:displayname", namespaces=_NS) or href.rstrip("/").rsplit("/", 1)[-1]
            lists.append({"name": name, "url": href})
        return lists

    def todos(self, calendar_url):
        """
        Get the raw iCalendar data of each task in a task list.

        :return:
            List of (href, iCalendar text) tuples.
        """
        results = []
        for response in self._request("REPORT", calendar_url, _REPORT_TODOS, depth=1):
            data = response.findtext("d:propstat/d:prop/c:calendar-data", namespaces=_NS)
            if data: results.append((response.findtext("d:href", namespaces=_NS), data))
        return results

    def _href(self, url, body, prop):
        for response in self._request("PROPFIND", url, body, depth=0):
            href = response.findtext(f"d:propstat/d:prop/{prop}/d:href", namespaces=_NS)
            if href: return urljoin(url, href)
        raise RuntimeError(f"No {prop} found at {url}")

    def _request(self, method, url, body, depth):
        log.debug("%s %s", method, url)
        response = self._session.request(
            method, url, data=body.encode(), timeout=30,
            headers={"Depth": str(depth), "Content-Type": "application/xml; charset=utf-8"},
        )
        response.raise_for_status()
        return ET.fromstring(response.content).findall("d:response", _NS)
