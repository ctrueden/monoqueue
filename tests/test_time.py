#!/usr/bin/env python
#
# This is free and unencumbered software released into the public domain.
# See the UNLICENSE file for details.
#
# ------------------------------------------------------------------------
# test_time.py
# ------------------------------------------------------------------------

import datetime
import unittest

from monoqueue import time

UTC = datetime.timezone.utc


class TestTime(unittest.TestCase):

    def test_str2dt_formats(self):
        expected = datetime.datetime(2026, 9, 17, 9, 44, tzinfo=UTC)
        self.assertEqual(expected, time.str2dt("2026-09-17T09:44:00Z"))
        self.assertEqual(expected, time.str2dt("2026-09-17T09:44:00.000Z"))
        self.assertEqual(expected, time.str2dt("2026-09-17 09:44 UTC"))
        self.assertEqual(expected, time.str2dt("2026-09-17T09:44:00"))
        self.assertEqual(expected, time.str2dt("2026-09-17T04:44:00-05:00"))

    def test_str2dt_invalid(self):
        with self.assertRaises(ValueError):
            time.str2dt("yesterday")

    def test_string_from_posix_is_utc(self):
        self.assertEqual("1970-01-01T00:00:00Z", time.string(0))

    def test_string_converts_offset(self):
        cdt = datetime.timezone(datetime.timedelta(hours=-5))
        dt = datetime.datetime(2026, 9, 17, 4, 44, tzinfo=cdt)
        self.assertEqual("2026-09-17T09:44:00Z", time.string(dt))

    def test_round_trip(self):
        s = "2026-09-17T09:44:00Z"
        self.assertEqual(s, time.string(time.str2dt(s)))


if __name__ == '__main__':
    unittest.main()
