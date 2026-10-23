#!/usr/bin/env python
#
# This is free and unencumbered software released into the public domain.
# See the UNLICENSE file for details.
#
# ------------------------------------------------------------------------
# test_caldav.py
# ------------------------------------------------------------------------

import unittest
from unittest import mock

from monoqueue import Monoqueue, caldav

BASE = "https://cloud.example.org/remote.php/dav/"
HOME = "/remote.php/dav/calendars/curtis/"

TIMEZONE = """BEGIN:VTIMEZONE
TZID:America/Chicago
BEGIN:STANDARD
DTSTART:19701101T020000
RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU
TZOFFSETFROM:-0500
TZOFFSETTO:-0600
END:STANDARD
BEGIN:DAYLIGHT
DTSTART:19700308T020000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU
TZOFFSETFROM:-0600
TZOFFSETTO:-0500
END:DAYLIGHT
END:VTIMEZONE
"""

# One task per resource, as CalDAV servers store them.
TASKS = {
    "review.ics": """BEGIN:VTODO
UID:review-pr
SUMMARY:Review appose PR
DESCRIPTION:See https://github.com/apposed/appose/pull/42 and also\\n https://forum.image.sc/t/123/4.
URL:https://github.com/apposed/appose/pull/42
DUE;TZID=America/Chicago:20261030T170000
PRIORITY:1
CATEGORIES:review,appose
CREATED:20261020T120000Z
LAST-MODIFIED:20261022T120000Z
DTSTAMP:20261022T120000Z
END:VTODO
""",
    "renew-cert.ics": """BEGIN:VTODO
UID:renew-cert
SUMMARY:Renew worf certificate
DUE;VALUE=DATE:20270104
DTSTAMP:20261023T120000Z
END:VTODO
""",
    "done.ics": """BEGIN:VTODO
UID:done
SUMMARY:Already done
STATUS:COMPLETED
DTSTAMP:20261023T120000Z
END:VTODO
""",
    "dropped.ics": """BEGIN:VTODO
UID:dropped
SUMMARY:Never mind
STATUS:CANCELLED
DTSTAMP:20261023T120000Z
END:VTODO
""",
}


def _ics(*todos):
    return "BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//Test\n" + TIMEZONE + "".join(todos) + "END:VCALENDAR\n"


def _multistatus(*responses):
    return ('<?xml version="1.0"?><d:multistatus xmlns:d="DAV:" '
            'xmlns:c="urn:ietf:params:xml:ns:caldav">'
            + "".join(f"<d:response>{r}</d:response>" for r in responses)
            + "</d:multistatus>")


def _response(href, prop):
    return f"<d:href>{href}</d:href><d:propstat><d:prop>{prop}</d:prop></d:propstat>"


def _calendar(name, displayname, *components):
    comps = "".join(f'<c:comp name="{c}"/>' for c in components)
    return _response(
        f"{HOME}{name}/",
        f"<d:displayname>{displayname}</d:displayname>"
        "<d:resourcetype><d:collection/><c:calendar/></d:resourcetype>"
        f"<c:supported-calendar-component-set>{comps}</c:supported-calendar-component-set>",
    )


def _fake_server(method, url, data=None, headers=None, timeout=None):
    body = data.decode()
    if method == "PROPFIND" and url == BASE:
        xml = _multistatus(_response(
            "/remote.php/dav/",
            "<d:current-user-principal><d:href>/remote.php/dav/principals/users/curtis/</d:href></d:current-user-principal>",
        ))
    elif method == "PROPFIND" and "calendar-home-set" in body:
        xml = _multistatus(_response(
            "/remote.php/dav/principals/users/curtis/",
            f"<c:calendar-home-set><d:href>{HOME}</d:href></c:calendar-home-set>",
        ))
    elif method == "PROPFIND" and url.endswith(HOME):
        xml = _multistatus(
            _response(HOME, "<d:resourcetype><d:collection/></d:resourcetype>"),
            _calendar("personal", "Personal", "VEVENT", "VTODO"),
            _calendar("work", "Work", "VTODO"),
            _calendar("contact_birthdays", "Birthdays", "VEVENT"),
        )
    elif method == "REPORT" and url.endswith(f"{HOME}work/"):
        xml = _multistatus(*(
            _response(f"{HOME}work/{name}", f"<c:calendar-data>{_ics(todo)}</c:calendar-data>")
            for name, todo in TASKS.items()
        ))
    elif method == "REPORT":
        xml = _multistatus()
    else:
        raise AssertionError(f"Unexpected request: {method} {url}")
    response = mock.Mock(content=xml.encode())
    response.raise_for_status = lambda: None
    return response


class TestCalDAV(unittest.TestCase):

    def setUp(self):
        patch = mock.patch("requests.Session.request", side_effect=_fake_server)
        self.request = patch.start()
        self.addCleanup(patch.stop)

    def test_task_lists(self):
        client = caldav.CalDAV(BASE.rstrip("/"), "curtis", "secret")
        lists = client.task_lists()
        self.assertEqual(
            [("Personal", f"https://cloud.example.org{HOME}personal/"),
             ("Work", f"https://cloud.example.org{HOME}work/")],
            [(c["name"], c["url"]) for c in lists],
        )

    def test_parse_todos(self):
        tasks = {t["uid"]: t for t in caldav.parse_todos(_ics(*TASKS.values()))}
        self.assertEqual({"review-pr", "renew-cert", "done", "dropped"}, set(tasks))

        pr = tasks["review-pr"]
        self.assertEqual("Review appose PR", pr["summary"])
        self.assertEqual("2026-10-30T22:00:00Z", pr["due"])  # 17:00 CDT in UTC.
        self.assertEqual(1, pr["priority"])
        self.assertEqual(["review", "appose"], pr["categories"])
        self.assertEqual(
            ["https://github.com/apposed/appose/pull/42", "https://forum.image.sc/t/123/4"],
            pr["links"],
        )
        self.assertEqual("2026-10-20T12:00:00Z", pr["created"])
        self.assertEqual("2026-10-22T12:00:00Z", pr["updated"])

        cert = tasks["renew-cert"]
        self.assertEqual("2027-01-04T23:59:59Z", cert["due"])  # All day.
        self.assertEqual(0, cert["priority"])
        self.assertEqual("2026-10-23T12:00:00Z", cert["created"])
        self.assertEqual("NEEDS-ACTION", cert["status"])

    def test_update(self):
        mq = Monoqueue({"rules": {}})
        caldav.update(mq, {"url": BASE, "username": "curtis", "password": "secret", "lists": "Work"})

        # Completed and cancelled tasks are skipped.
        self.assertEqual(
            {f"https://cloud.example.org{HOME}work/{name}" for name in ("review.ics", "renew-cert.ics")},
            set(mq.items),
        )
        item = mq.item(f"https://cloud.example.org{HOME}work/review.ics")
        self.assertEqual("Review appose PR", item["title"])
        self.assertEqual("2026-10-30T22:00:00Z", item["due"])
        self.assertEqual("Work", item["task"]["list"])

        # Only the Work list was queried for tasks.
        reports = [c.args[1] for c in self.request.call_args_list if c.args[0] == "REPORT"]
        self.assertEqual([f"https://cloud.example.org{HOME}work/"], reports)

        mq._score()
        self.assertIn("seconds_until_due", item)

    def test_link_template(self):
        mq = Monoqueue({"rules": {}})
        caldav.update(mq, {
            "url": BASE,
            "link": "https://cloud.example.org/apps/tasks/#/calendars/{calendar}/tasks/{task}",
        })
        self.assertIn(
            "https://cloud.example.org/apps/tasks/#/calendars/work/tasks/review.ics",
            mq.items,
        )
        self.assertEqual(2, len(mq.items))

    def test_verify(self):
        self.assertIs(False, caldav._verify("false"))
        self.assertIs(True, caldav._verify("true"))
        self.assertEqual("/etc/ssl/certs", caldav._verify("/etc/ssl/certs"))


if __name__ == '__main__':
    unittest.main()
