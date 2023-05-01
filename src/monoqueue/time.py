#!/usr/bin/env python
#
# This is free and unencumbered software released into the public domain.
# See the UNLICENSE file for details.
#
# ------------------------------------------------------------------------
# time.py
# ------------------------------------------------------------------------

"""
Utility functions for working with dates and times.
"""

import datetime, re

from typing import Union


def now() -> datetime.datetime:
    """
    Get the current date, in UTC.
    :return:
        A timestamp representing the current moment.
    """
    return datetime.datetime.now(tz=datetime.timezone.utc)


def str2dt(timestamp: str) -> datetime.datetime:
    """
    Parse a string to a datetime object.
    :param timestamp:
        String representation of a timestamp in
        YYYY-MM-DDTHH:MM:SSZ or YYYY-MM-DDTHH:MM:SS.sssZ format.
    :return:
        Parsed datetime.datetime object of the timestamp.
    """
    # Credit: https://stackoverflow.com/a/969324/1207769
    if re.match("\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\\.\d+Z$", timestamp):
        # GitHub style, without millisecond.
        return datetime.datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%S.%f%z")
    if re.match("\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", timestamp):
        # Discourse style, with millisecond.
        return datetime.datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%S%z")
    raise ValueError(f"Weird timestamp: {timestamp}")


def string(timestamp: Union[datetime.datetime, int]) -> str:
    """
    Converts a timestamp to an ISO-8601-formatted timestamp string.
    :param timestamp:
        Timestamp, either as a datetime object, or an
        int-valued POSIX timestamp (seconds since epoch).
    :return:
        Timestamp string in ISO 8601 format.
    """
    if isinstance(timestamp, int):
        timestamp = datetime.datetime.fromtimestamp(timestamp)
    if not hasattr(timestamp, "isoformat"):
        raise ValueError(f"Invalid timestamp type: {type(timestamp)}")
    s: str = timestamp.isoformat()
    plus = s.find("+")
    if plus >= 0: s = s[:plus]
    return s + "Z"


def age(timestamp: Union[datetime.datetime, str]) -> datetime.timedelta:
    """
    Gets the amount of time that has passed since the given timestamp.
    :param timestamp:
        A datetime.datetime, or string to be parsed as such.
    :return:
        The datetime.timedelta of now() minus the timestamp.
    """
    if isinstance(timestamp, str):
        timestamp = str2dt(timestamp)

    return now() - timestamp


def days_later(days: int) -> datetime.datetime:
    """
    Gets a timestamp for a number of days in the future.
    :param days:
        The number of days in the future.
    :return:
        The timestamp for that many days in the future.
    """
    return now() + datetime.timedelta(days=days)
