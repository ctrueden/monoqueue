#
# This is free and unencumbered software released into the public domain.
# See the UNLICENSE file for details.
#
# ------------------------------------------------------------------------
# imap.py
# ------------------------------------------------------------------------

"""
Routines to read email from an IMAP server, such as Dovecot or Fastmail.

The messages of the configured mailboxes become action items, one per
thread: messages are grouped by their References and In-Reply-To headers,
or failing that their subjects, among the fetched messages only. A thread
is keyed by its root message, as a mid: URL (RFC 2392), so it stays the
same item as its messages move between folders or gain labels. Mail about a GitHub issue or PR, or a
Discourse topic, becomes part of that item instead.

Fields for use in rules:

    email/label -> most urgent $labelN keyword (1 = most), as set by
                   Roundcube's thunderbird_labels plugin or Thunderbird
    email/keywords -> all keywords of the thread's messages
    email/unread -> whether any message is unread
    email/flagged -> whether any message is flagged (starred)
    email/mailboxes -> folders the messages are in
    email/from -> sender of the thread's first message
    email/senders -> addresses of all senders
    email/count -> number of messages
"""

from __future__ import annotations

import contextlib
import datetime
import email
import email.policy
import email.utils
import html
import imaplib
import re
import ssl
import subprocess
import tempfile
from collections import Counter
from typing import Any
from urllib.parse import quote

from . import time
from .caldav import _verify
from .log import log

# Fetch at most this much of each message: enough for its headers and text.
_MAX_BYTES = 65536
# Keep at most this much of the latest message's text, as the description.
_MAX_TEXT = 4000
# Fetch this many messages per request.
_BATCH = 100
# Join messages into a thread by subject only if it is at least this long.
_MIN_SUBJECT = 12

_GITHUB_ID = re.compile(
    "^([\\w.-]+)/([\\w.-]+)/(issues|pull)/(\\d+)(?:/[^@]*)?@github\\.com$"
)
_LABEL = re.compile("^\\$label(\\d+)$", re.IGNORECASE)
_REPLY_PREFIX = re.compile(
    "^\\s*((re|fwd?|aw|wg|sv|antw)(\\[\\d+\\])?\\s*:\\s*)+", re.IGNORECASE
)
_TOKEN = re.compile(
    b'\\s*(?:(\\()|(\\))|"((?:\\\\.|[^"\\\\])*)"|([^\\s()"\\[]+(?:\\[[^\\]]*\\])?(?:<\\d+>)?))'
)


def update(mq, config):
    mailboxes = [
        m.strip() for m in config.get("mailboxes", "INBOX").split(",") if m.strip()
    ]
    search = config.get("search", "ALL")
    link = config.get("link")

    conn = connect(config)
    try:
        messages = []
        for mailbox in mailboxes:
            messages += fetch(conn, mailbox, search)
    finally:
        with contextlib.suppress(imaplib.IMAP4.error, OSError):
            conn.logout()

    for url, data in items(dedupe(messages), link):
        mq.put(url, data)


def connect(config):
    """
    Connect to the IMAP server, either by running the configured command,
    which speaks IMAP on stdin/stdout, already logged in (e.g. Dovecot's
    doveadm exec imap), or over the network, logging in.
    """
    command = config.get("command")
    if command:
        log.debug("Running %s", command)
        return _Stream(command)

    host = config.get("host", "localhost")
    mode = config.get("ssl", "true").lower()
    verify = _verify(config.get("verify", "true"))
    context = ssl.create_default_context(
        cafile=verify if isinstance(verify, str) and not verify.endswith("/") else None,
        capath=verify if isinstance(verify, str) and verify.endswith("/") else None,
    )
    if verify is False:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

    log.debug("Connecting to %s", host)
    if mode == "starttls":
        conn = imaplib.IMAP4(host, int(config.get("port", 143)))
        conn.starttls(ssl_context=context)
    elif mode in ("false", "no", "off", "0"):
        conn = imaplib.IMAP4(host, int(config.get("port", 143)))
    else:
        conn = imaplib.IMAP4_SSL(
            host, int(config.get("port", 993)), ssl_context=context
        )
    conn.login(config["username"], config["password"])
    return conn


class _Stream(imaplib.IMAP4_stream):
    """
    An IMAP connection to a command, whose stderr goes to the debug log
    rather than the terminal (e.g. doveadm's disconnection notices).
    """

    def open(self, host=None, port=None, timeout=None):
        self.host = self.port = self.sock = self.file = None
        # NB: Kept open until shutdown, so no context manager here.
        self.stderr = tempfile.TemporaryFile()  # noqa: SIM115
        self.process = subprocess.Popen(
            self.command,
            bufsize=imaplib.DEFAULT_BUFFER_SIZE,
            shell=True,
            close_fds=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.stderr,
        )
        self.writefile = self.process.stdin
        self.readfile = self.process.stdout

    def shutdown(self):
        super().shutdown()
        self.stderr.seek(0)
        output = self.stderr.read().decode(errors="replace").strip()
        self.stderr.close()
        if output:
            log.debug("%s: %s", self.command, output)


def fetch(conn, mailbox: str, search: str = "ALL") -> list[dict[str, Any]]:
    """
    Fetch the messages of a mailbox that match an IMAP search.

    :return:
        List of dicts describing each message.
    """
    log.debug("Reading mailbox %s", mailbox)
    typ, data = conn.select(_quote(mailbox), readonly=True)
    if typ != "OK":
        raise RuntimeError(f"Cannot open mailbox {mailbox}: {data}")
    typ, data = conn.uid("SEARCH", search)
    if typ != "OK":
        raise RuntimeError(f"Cannot search mailbox {mailbox}: {data}")
    uids = data[0].split() if data and data[0] else []

    messages = []
    for i in range(0, len(uids), _BATCH):
        uid_set = b",".join(uids[i : i + _BATCH]).decode()
        for response in _fetch(conn, uid_set):
            message = parse_message(response, mailbox)
            if message:
                messages.append(message)
    return messages


def _fetch(conn, uid_set: str) -> list[dict[str, Any]]:
    # Dovecot can say where each message of a virtual mailbox really is.
    # Other servers reject these items, so then do without.
    extra = " X-MAILBOX X-REAL-UID" if getattr(conn, "_mq_real", True) else ""
    query = f"(UID FLAGS INTERNALDATE{extra} BODY.PEEK[]<0.{_MAX_BYTES}>)"
    try:
        typ, data = conn.uid("FETCH", uid_set, query)
    except imaplib.IMAP4.error:
        if not extra:
            raise
        conn._mq_real = False
        return _fetch(conn, uid_set)
    if typ != "OK":
        raise RuntimeError(f"Cannot fetch messages: {data}")
    return parse_fetch(data)


def parse_fetch(data) -> list[dict[str, Any]]:
    """
    Parse the data of an imaplib FETCH response into a dict per message,
    from each data item name (e.g. UID or BODY[]<0>) to its value.
    """
    tokens = []
    for part in data or []:
        if isinstance(part, tuple):
            head, literal = part
            tokens += _tokenize(re.sub(b"\\{\\d+\\}$", b"", head))
            tokens.append(("value", literal))
        elif part:
            tokens += _tokenize(part)

    responses = []
    pos = 0
    while pos < len(tokens):
        pos += 1  # Skip the sequence number.
        if pos >= len(tokens) or tokens[pos][0] != "(":
            break
        values, pos = _parse_list(tokens, pos + 1)
        responses.append(
            {
                values[i].upper() if isinstance(values[i], str) else values[i]: values[
                    i + 1
                ]
                for i in range(0, len(values) - 1, 2)
            }
        )
    return responses


def _tokenize(text: bytes):
    tokens = []
    pos = 0
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m or m.end() == pos:
            break
        pos = m.end()
        if m.group(1):
            tokens.append(("(", None))
        elif m.group(2):
            tokens.append((")", None))
        elif m.group(3) is not None:
            tokens.append(("value", re.sub(b"\\\\(.)", b"\\1", m.group(3))))
        elif m.group(4):
            atom = m.group(4).decode(errors="replace")
            tokens.append(("value", None if atom == "NIL" else atom))
    return tokens


def _parse_list(tokens, pos):
    values = []
    while pos < len(tokens):
        kind, value = tokens[pos]
        pos += 1
        if kind == ")":
            return values, pos
        if kind == "(":
            value, pos = _parse_list(tokens, pos)
        values.append(value)
    return values, pos


def parse_message(response: dict[str, Any], mailbox: str) -> dict[str, Any] | None:
    """
    Describe a message, from its parsed FETCH response.
    """
    raw = next(
        (
            v
            for k, v in response.items()
            if isinstance(k, str) and k.startswith("BODY[")
        ),
        None,
    )
    if raw is None:
        return None
    msg = email.message_from_bytes(raw, policy=email.policy.default)

    flags = [f for f in response.get("FLAGS") or [] if isinstance(f, str)]
    received = _internaldate(response.get("INTERNALDATE"))
    date = _date(_header(msg, "Date")) or received
    real_mailbox = response.get("X-MAILBOX")
    if isinstance(real_mailbox, bytes):
        real_mailbox = real_mailbox.decode(errors="replace")
    real_uid = response.get("X-REAL-UID")

    ids = _ids(_header(msg, "Message-ID"))
    topic = _header(msg, "X-Discourse-Topic-Id").strip()
    archive = _ids(_header(msg, "List-Archive"))
    return {
        "message_id": ids[0] if ids else None,
        "references": _ids(_header(msg, "References")),
        "in_reply_to": _ids(_header(msg, "In-Reply-To")),
        "subject": " ".join(_header(msg, "Subject").split()),
        "from": " ".join(_header(msg, "From").split()),
        "sender": email.utils.parseaddr(_header(msg, "From"))[1].lower(),
        "date": date,
        "received": received or date,
        "flags": flags,
        "mailbox": real_mailbox or mailbox,
        "uid": int(real_uid if real_mailbox and real_uid else response.get("UID")),
        "forum": _forum(archive[0] if archive else _header(msg, "List-Archive"), topic),
        "text": _text(msg),
    }


def dedupe(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Merge copies of the same message, e.g. one in two virtual mailboxes.
    """
    unique = {}
    for message in messages:
        key = message["message_id"] or (message["mailbox"], message["uid"])
        if key in unique:
            seen = unique[key]
            seen["flags"] = seen["flags"] + [
                f for f in message["flags"] if f not in seen["flags"]
            ]
        else:
            unique[key] = message
    return list(unique.values())


def threads(messages: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """
    Group messages into threads, by the Message-IDs they share: their
    own, and those of the messages they reply to or reference.

    :return:
        List of threads, each a list of messages, oldest first.
    """
    parent = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    keys = []
    for i, message in enumerate(messages):
        key = message["message_id"] or f"#{i}"
        keys.append(key)
        for other in message["references"] + message["in_reply_to"]:
            parent[find(other)] = find(key)
        # Some mailers drop References, and some relays rewrite Message-IDs,
        # so also join messages with the same (not too short) subject.
        subject = " ".join(_REPLY_PREFIX.sub("", message["subject"]).lower().split())
        if len(subject) >= _MIN_SUBJECT:
            parent[find(f"subject:{subject}")] = find(key)

    groups = {}
    for key, message in zip(keys, messages):
        groups.setdefault(find(key), []).append(message)
    return [sorted(g, key=lambda m: m["date"]) for g in groups.values()]


def root_id(thread: list[dict[str, Any]]) -> str | None:
    """
    Get the Message-ID of a thread's root message, which need not be among
    its messages: the one that most of them reference first (or reply to,
    lacking References), else that of the oldest message.
    """
    roots = Counter()
    for message in thread:
        root = (
            message["references"] or message["in_reply_to"] or [message["message_id"]]
        )[0]
        if root:
            roots[root] += 1
    if not roots:
        return None
    # NB: Counter keeps insertion order, i.e. oldest first, among ties.
    return roots.most_common(1)[0][0]


def thread_url(thread: list[dict[str, Any]]) -> str | None:
    """
    Get the URL of the action item for a thread: that of its GitHub issue
    or PR, or Discourse topic, if it is about one; else a mid: URL.
    """
    for message in thread:
        for message_id in (
            [message["message_id"]] + message["references"] + message["in_reply_to"]
        ):
            m = _GITHUB_ID.match(message_id or "")
            if m:
                return f"https://github.com/{m.group(1)}/{m.group(2)}/{m.group(3)}/{m.group(4)}"
    for message in thread:
        if message["forum"]:
            return message["forum"]
    root = root_id(thread)
    return f"mid:{quote(root, safe='@!$&*+=^_`{|}~.-')}" if root else None


def items(messages: list[dict[str, Any]], link: str | None = None):
    """
    Make action items of messages, one per thread.

    :param link:
        URL template for opening a message in a web app, with {mailbox},
        {uid} and {message_id} placeholders.
    :return:
        Iterator of (url, data) pairs.
    """
    for thread in threads(messages):
        url = thread_url(thread)
        first, latest = thread[0], thread[-1]
        if url is None:
            # No Message-IDs at all: key by location, the best we can do.
            url = f"imap:///{quote(first['mailbox'])};UID={first['uid']}"

        flags = []
        for message in thread:
            flags += [f for f in message["flags"] if f not in flags]
        labels = [int(m.group(1)) for m in (_LABEL.match(f) for f in flags) if m]
        data = {
            "title": _REPLY_PREFIX.sub("", first["subject"]) or "(no subject)",
            "created": time.string(first["date"]),
            "updated": time.string(max(m["received"] for m in thread)),
            "description": latest["text"],
            "email": {
                "label": min(labels) if labels else None,
                "keywords": sorted(f for f in flags if not f.startswith("\\")),
                "unread": any("\\Seen" not in m["flags"] for m in thread),
                "flagged": "\\Flagged" in flags,
                "mailboxes": sorted({m["mailbox"] for m in thread}),
                "from": first["from"],
                "senders": sorted({m["sender"] for m in thread if m["sender"]}),
                "count": len(thread),
                "messages": [
                    {
                        "message_id": m["message_id"],
                        "subject": m["subject"],
                        "from": m["from"],
                        "date": time.string(m["date"]),
                        "mailbox": m["mailbox"],
                        "uid": m["uid"],
                        "flags": m["flags"],
                    }
                    for m in thread
                ],
            },
        }
        if link and not url.startswith("https://"):
            data["link"] = link.format(
                mailbox=quote(latest["mailbox"], safe=""),
                uid=latest["uid"],
                message_id=quote(latest["message_id"] or "", safe=""),
            )
        yield url, data


def _quote(mailbox: str) -> str:
    return '"' + mailbox.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _header(msg, name: str) -> str:
    try:
        value = msg.get(name)
        return str(value) if value is not None else ""
    except Exception:  # noqa: BLE001
        # A malformed header; fall back to its raw value.
        for key, value in msg.raw_items():
            if key.lower() == name.lower():
                return str(value)
        return ""


def _ids(value: str) -> list[str]:
    ids = re.findall("<([^<>\\s]+)>", value)
    if not ids and value.strip() and " " not in value.strip():
        ids = [value.strip()]
    return ids


def _forum(archive: str, topic: str) -> str | None:
    if not topic.isdigit():
        return None
    m = re.match("(https?://[^/]+)/", archive or "")
    return f"{m.group(1)}/t/{topic}" if m else None


def _date(value: str) -> datetime.datetime | None:
    try:
        date = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    # NB: Missing or bogus dates often parse as the epoch.
    if date is None or date.year < 1980:
        return None
    return time.utc(date)


def _internaldate(value) -> datetime.datetime | None:
    if isinstance(value, bytes):
        value = value.decode()
    if not value:
        return None
    try:
        return time.utc(
            datetime.datetime.strptime(value.strip(), "%d-%b-%Y %H:%M:%S %z")
        )
    except ValueError:
        return None


def _text(msg) -> str:
    """
    Get a message's text, as plain text, truncated.
    """
    try:
        part = msg.get_body(preferencelist=("plain", "html"))
        content = part.get_content() if part else ""
    except Exception:  # noqa: BLE001
        # E.g. a truncated or malformed message, or an unknown charset.
        return ""
    if not isinstance(content, str):
        return ""
    if part.get_content_subtype() == "html":
        content = re.sub("(?is)<(script|style)\\b.*?</\\1>", "", content)
        content = re.sub("(?i)<br\\s*/?>|</(p|div|tr|li|h\\d)>", "\n", content)
        content = html.unescape(re.sub("<[^>]+>", "", content))
    content = re.sub("[ \\t\\r\\f\\v]+\n", "\n", content)
    content = re.sub("\n{3,}", "\n\n", content).strip()
    if len(content) > _MAX_TEXT:
        content = content[:_MAX_TEXT] + "\n[...truncated]"
    return content
