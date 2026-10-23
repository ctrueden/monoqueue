#!/usr/bin/env python
#
# This is free and unencumbered software released into the public domain.
# See the UNLICENSE file for details.
#
# ------------------------------------------------------------------------
# test_urls.py
# ------------------------------------------------------------------------

import unittest

from monoqueue.urls import normalize


class TestUrls(unittest.TestCase):

    def test_fragment_and_tracking(self):
        self.assertEqual(
            "https://github.com/scijava/pombast/issues/7",
            normalize("https://github.com/scijava/pombast/issues/7#issuecomment-123"),
        )
        self.assertEqual(
            "https://example.com/page?id=5",
            normalize("https://Example.COM/page/?utm_source=mail&id=5&fbclid=xyz"),
        )

    def test_non_http(self):
        self.assertEqual("about:newtab", normalize("about:newtab"))
        self.assertEqual("mailto:a@b.c", normalize("mailto:a@b.c"))

    def test_discourse_topic(self):
        topic = "https://forum.image.sc/t/123"
        self.assertEqual(topic, normalize("https://forum.image.sc/t/my-topic/123"))
        self.assertEqual(topic, normalize("https://forum.image.sc/t/my-topic/123/1"))
        self.assertEqual(topic, normalize("https://forum.image.sc/t/123/1"))
        self.assertEqual(topic, normalize("https://forum.image.sc/t/123/"))

    def test_discourse_post_kept(self):
        post = "https://forum.image.sc/t/123/4"
        self.assertEqual(post, normalize("https://forum.image.sc/t/my-topic/123/4"))
        self.assertEqual(post, normalize("https://forum.image.sc/t/renamed-topic/123/4"))
        self.assertEqual(post, normalize(post))

    def test_discourse_hosts_only(self):
        url = "https://example.com/t/my-topic/123"
        self.assertEqual(url, normalize(url))
        self.assertEqual(
            "https://forum.example.com/t/123",
            normalize("https://forum.example.com/t/x/123", {"forum.example.com"}),
        )

    def test_discourse_non_topic(self):
        url = "https://forum.image.sc/t/just-a-slug"
        self.assertEqual(url, normalize(url))


if __name__ == '__main__':
    unittest.main()
