#
# This is free and unencumbered software released into the public domain.
# See the UNLICENSE file for details.
#
# ------------------------------------------------------------------------
# test_imap.py
# ------------------------------------------------------------------------

import imaplib
import unittest
from unittest import mock

from monoqueue import Monoqueue, imap


def _message(
    message_id,
    subject,
    date="Wed, 21 Oct 2026 14:01:06 +0000",
    sender="Jane Doe <jane@example.org>",
    references=None,
    extra="",
    body="Hello.",
):
    headers = [f"From: {sender}", f"Subject: {subject}", f"Date: {date}"]
    if message_id:
        headers.append(f"Message-ID: <{message_id}>")
    if references:
        headers.append(f"In-Reply-To: <{references[-1]}>")
        headers.append("References: " + " ".join(f"<{r}>" for r in references))
    if extra:
        headers.append(extra)
    return ("\r\n".join(headers) + "\r\n\r\n" + body + "\r\n").encode()


# Mailbox -> list of (uid, flags, real mailbox, real uid, message), as
# Dovecot's virtual mailboxes give them.
MAILBOXES = {
    "Virtual/1-Urgent": [
        (
            6,
            "\\Seen $LABEL1",
            "Archive/2026",
            9901,
            _message("cert@wisc.edu", "Shorter certificate lifespans"),
        ),
        (
            39,
            "$LABEL1",
            "INBOX",
            13086,
            _message(
                "ctrueden/tasks/issues/7/4397835586@github.com",
                "Re: [ctrueden/tasks] Add section on logo licensing (#7)",
                sender="bevilacqc <notifications@github.com>",
                references=["ctrueden/tasks/issues/7@github.com"],
            ),
        ),
    ],
    "Virtual/4-Later": [
        # A thread: a question, and a reply, both labeled.
        (
            1,
            "\\Seen $LABEL4",
            "Archive/2025",
            10,
            _message(
                "q@example.org",
                "Packaging Java programs with conda",
                date="Mon, 01 Sep 2025 10:00:00 +0200",
            ),
        ),
        (
            2,
            "\\Seen \\Flagged $LABEL4",
            "Archive/2025",
            11,
            _message(
                "a@example.org",
                "RE: Packaging Java programs with conda",
                date="Tue, 02 Sep 2025 10:00:00 +0200",
                sender="Curtis <curtis@example.org>",
                references=["q@example.org"],
            ),
        ),
        # Same subject, but its References were dropped by some mailer.
        (
            3,
            "\\Seen $LABEL4",
            "Archive/2025",
            12,
            _message(
                "b@example.org",
                "Re: Packaging Java programs with conda",
                date="Wed, 03 Sep 2025 10:00:00 +0200",
            ),
        ),
        # A forum topic.
        (
            4,
            "\\Seen $LABEL4",
            "Archive/2025",
            13,
            _message(
                "discourse/post/372243@forum.image.sc",
                "[Image.sc Forum] Update site password",
                extra="List-Archive: https://forum.image.sc/t/update-site-password/122537\r\n"
                "X-Discourse-Topic-Id: 122537",
            ),
        ),
    ],
    "Virtual/5-Someday": [
        # Also labeled 1, so in the Urgent mailbox too.
        (
            7,
            "\\Seen $LABEL1 $LABEL5",
            "Archive/2026",
            9901,
            _message("cert@wisc.edu", "Shorter certificate lifespans"),
        ),
    ],
}


class FakeIMAP:
    """
    Just enough of an imaplib connection, answering as Dovecot does.
    """

    def __init__(self, real=True):
        self.real = real
        self.mailbox = None
        self.fetches = []

    def select(self, mailbox, readonly=False):
        assert readonly
        self.mailbox = mailbox.strip('"')
        return "OK", [str(len(MAILBOXES[self.mailbox])).encode()]

    def uid(self, command, *args):
        messages = MAILBOXES[self.mailbox]
        if command == "SEARCH":
            return "OK", [" ".join(str(m[0]) for m in messages).encode()]
        uid_set, query = args
        self.fetches.append(query)
        if "X-MAILBOX" in query and not self.real:
            raise imaplib.IMAP4.error(
                "FETCH command error: BAD [b'Error in IMAP command']"
            )
        uids = {int(u) for u in uid_set.split(",")}
        data = []
        for seq, (uid, flags, real_mailbox, real_uid, raw) in enumerate(messages, 1):
            if uid not in uids:
                continue
            real = (
                f' X-MAILBOX "{real_mailbox}" X-REAL-UID {real_uid}'
                if self.real
                else ""
            )
            head = (
                f'{seq} (UID {uid} FLAGS ({flags}) INTERNALDATE "21-Oct-2026 14:01:25 -0500"'
                f"{real} BODY[]<0> {{{len(raw)}}}"
            )
            data += [(head.encode(), raw), b")"]
        return "OK", data

    def logout(self):
        pass


CONFIG = {
    "command": "true",
    "mailboxes": "Virtual/1-Urgent, Virtual/4-Later, Virtual/5-Someday",
    "link": "https://mail.example.org/?_task=mail&_action=show&_mbox={mailbox}&_uid={uid}",
}


class TestIMAP(unittest.TestCase):
    def update(self, conn=None):
        mq = Monoqueue({"rules": {}})
        with mock.patch.object(imap, "connect", return_value=conn or FakeIMAP()):
            imap.update(mq, CONFIG)
        return mq

    def test_parse_fetch(self):
        data = [
            (
                (
                    b'1 (UID 6 FLAGS (\\Seen $LABEL1) INTERNALDATE "21-Jan-2026 14:01:25 -0600" '
                    b'X-MAILBOX "Archive/2026" PREVIEW {5}'
                ),
                b"Hi (x",
            ),
            (b" BODY[]<0> {4}", b"Body"),
            b")",
            b'2 (UID 7 FLAGS () X-MAILBOX NIL BODY[]<0> "")',
        ]
        first, second = imap.parse_fetch(data)
        self.assertEqual("6", first["UID"])
        self.assertEqual(["\\Seen", "$LABEL1"], first["FLAGS"])
        self.assertEqual(b"21-Jan-2026 14:01:25 -0600", first["INTERNALDATE"])
        self.assertEqual(b"Archive/2026", first["X-MAILBOX"])
        self.assertEqual(b"Hi (x", first["PREVIEW"])
        self.assertEqual(b"Body", first["BODY[]<0>"])
        self.assertEqual([], second["FLAGS"])
        self.assertIsNone(second["X-MAILBOX"])

    def test_items(self):
        mq = self.update()
        mid = "mid:q@example.org"
        self.assertEqual(
            {
                "mid:cert@wisc.edu",
                "https://github.com/ctrueden/tasks/issues/7",
                mid,
                "https://forum.image.sc/t/122537",
            },
            set(mq.items),
        )

        # One item per thread, keyed by its root, titled by its first message.
        item = mq.item(mid)
        self.assertEqual("Packaging Java programs with conda", item["title"])
        self.assertEqual(3, item["email"]["count"])
        self.assertEqual(4, item["email"]["label"])
        self.assertTrue(item["email"]["flagged"])
        self.assertFalse(item["email"]["unread"])
        self.assertEqual(["Archive/2025"], item["email"]["mailboxes"])
        self.assertEqual(
            ["curtis@example.org", "jane@example.org"], item["email"]["senders"]
        )
        self.assertEqual("2025-09-01T08:00:00Z", item["created"])
        self.assertEqual("Hello.", item["description"])
        # Opened at the latest message, where it really is.
        self.assertEqual(
            "https://mail.example.org/?_task=mail&_action=show&_mbox=Archive%2F2025&_uid=12",
            item["link"],
        )
        self.assertEqual(item["link"], mq.open_url(mid))

    def test_labels(self):
        mq = self.update()
        # A message in two label mailboxes is one message, most urgently labeled.
        cert = mq.item("mid:cert@wisc.edu")
        self.assertEqual(1, cert["email"]["count"])
        self.assertEqual(1, cert["email"]["label"])
        self.assertEqual(["$LABEL1", "$LABEL5"], cert["email"]["keywords"])

        # Mail about a GitHub issue joins its item, opened as the issue.
        issue = mq.item("https://github.com/ctrueden/tasks/issues/7")
        self.assertEqual(1, issue["email"]["label"])
        self.assertTrue(issue["email"]["unread"])
        self.assertNotIn("link", issue)
        self.assertEqual(
            "[ctrueden/tasks] Add section on logo licensing (#7)", issue["title"]
        )

    def test_without_real_mailbox(self):
        # Servers other than Dovecot reject X-MAILBOX; then use the
        # mailbox searched, and its UIDs.
        conn = FakeIMAP(real=False)
        mq = self.update(conn)
        self.assertNotIn("X-MAILBOX", conn.fetches[-1])
        self.assertEqual(
            "https://mail.example.org/?_task=mail&_action=show&_mbox=Virtual%2F1-Urgent&_uid=6",
            mq.item("mid:cert@wisc.edu")["link"],
        )

    def test_root_id(self):
        def message(message_id, references=(), date=0):
            return {
                "message_id": message_id,
                "references": list(references),
                "in_reply_to": [],
                "date": date,
            }

        # The root stays put as replies are labeled, even if it is not.
        self.assertEqual("a", imap.root_id([message("a")]))
        self.assertEqual("a", imap.root_id([message("a"), message("c", ["a", "b"])]))
        self.assertEqual(
            "a", imap.root_id([message("b", ["a"]), message("c", ["a", "b"])])
        )

    def test_short_subjects(self):
        messages = [
            imap.parse_message(
                {"UID": "1", "BODY[]<0>": _message(f"{n}@x", "Re: Hello")}, "INBOX"
            )
            for n in (1, 2)
        ]
        # Too short to mean the same thread.
        self.assertEqual(2, len(imap.threads(messages)))

    def test_html(self):
        raw = (
            b"Subject: Hi\r\nMessage-ID: <h@x>\r\nContent-Type: text/html\r\n\r\n"
            b"<html><style>p {}</style><p>One &amp; two</p><p>Three</p></html>"
        )
        message = imap.parse_message({"UID": "1", "BODY[]<0>": raw}, "INBOX")
        self.assertEqual("One & two\nThree", message["text"])


if __name__ == "__main__":
    unittest.main()
