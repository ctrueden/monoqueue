#!/usr/bin/env python
#
# This is free and unencumbered software released into the public domain.
# See the UNLICENSE file for details.
#
# ------------------------------------------------------------------------
# urls.py
# ------------------------------------------------------------------------

"""
Utility functions for normalizing action item URLs.

The same action item is often reachable by several URLs: a browser tab
with a #fragment, an email link with utm_* tracking parameters, or a
Discourse post URL whose slug changed when the topic title was edited.
Normalizing them means items from different sources merge into one.
"""

import re
from collections.abc import Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Hosts known to run Discourse, in addition to any configured sources.
DISCOURSE_HOSTS = {"forum.image.sc"}

_TRACKING_PARAM = re.compile("^(utm_.*|fbclid|gclid|mc_cid|mc_eid)$")


def normalize(url: str, discourse_hosts: Iterable[str] = DISCOURSE_HOSTS) -> str:
    """
    Normalize a URL, so that equivalent URLs compare equal.

    * Lowercase the scheme and host.
    * Strip the #fragment and any tracking query parameters.
    * Strip any trailing slash.
    * For Discourse topics, strip the slug, and the post number if it is 1:
      /t/my-topic/123 and /t/123/1 become /t/123, while /t/my-topic/123/4
      becomes /t/123/4. Other post numbers are kept, since separate posts
      of the same topic can be separate action items.

    :param url:
        The URL to normalize.
    :param discourse_hosts:
        Hosts whose /t/ paths are Discourse topics.
    :return:
        The normalized URL, or the original URL if it is not http(s).
    """
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"): return url

    host = parts.netloc.lower()
    query = urlencode([
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not _TRACKING_PARAM.match(k)
    ])
    path = parts.path
    if host in discourse_hosts:
        path = _discourse_path(path)
    if len(path) > 1: path = path.rstrip("/")

    return urlunsplit((scheme, host, path, query, ""))


def _discourse_path(path: str) -> str:
    segments = [s for s in path.split("/") if s]
    if len(segments) < 2 or segments[0] != "t": return path
    segments = segments[1:]

    # Drop the slug, if any. NB: A purely numeric slug would be mistaken
    # for a topic ID, but Discourse slugs are rarely only digits.
    if not segments[0].isdigit(): segments = segments[1:]
    if not segments or not all(s.isdigit() for s in segments[:2]): return path

    topic = segments[0]
    post = segments[1] if len(segments) > 1 else "1"
    return f"/t/{topic}" if post == "1" else f"/t/{topic}/{post}"
