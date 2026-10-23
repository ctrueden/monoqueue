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

import datetime
import re
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
        String representation of a timestamp in ISO 8601 format,
        e.g. YYYY-MM-DDTHH:MM:SSZ or YYYY-MM-DDTHH:MM:SS.sssZ, or
        YYYY-MM-DD HH:MM UTC. Timestamps without a timezone are UTC.
    :return:
        Parsed datetime.datetime object of the timestamp.
    """
    # Credit: https://stackoverflow.com/a/969324/1207769
    if re.match("\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}\\.\\d+Z$", timestamp):
        # GitHub style, without millisecond.
        return datetime.datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%S.%f%z")
    if re.match("\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}Z$", timestamp):
        # Discourse style, with millisecond.
        return datetime.datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%S%z")
    m = re.match("(\\d{4}-\\d{2}-\\d{2})[T ](\\d{2}:\\d{2}(:\\d{2})?)( UTC)?$", timestamp)
    if m:
        # Naive or explicitly UTC, e.g. "2026-09-17 09:44 UTC"; assume UTC.
        hms = m.group(2) if m.group(3) else m.group(2) + ":00"
        return datetime.datetime.fromisoformat(f"{m.group(1)}T{hms}+00:00")
    try:
        return utc(datetime.datetime.fromisoformat(timestamp.replace("Z", "+00:00")))
    except ValueError:
        raise ValueError(f"Weird timestamp: {timestamp}")


def utc(timestamp: datetime.datetime) -> datetime.datetime:
    """
    Convert a datetime to UTC.
    :param timestamp:
        The datetime to convert. If naive, it is assumed to be UTC already.
    :return:
        A UTC-aware datetime.datetime object.
    """
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=datetime.timezone.utc)
    return timestamp.astimezone(datetime.timezone.utc)


def string(timestamp: Union[datetime.datetime, int]) -> str:
    """
    Converts a timestamp to an ISO-8601-formatted UTC timestamp string.
    :param timestamp:
        Timestamp, either as a datetime object (naive means UTC), or
        a POSIX timestamp (seconds since epoch).
    :return:
        Timestamp string in ISO 8601 format.
    """
    if isinstance(timestamp, (int, float)):
        timestamp = datetime.datetime.fromtimestamp(timestamp, tz=datetime.timezone.utc)
    if not isinstance(timestamp, datetime.datetime):
        raise ValueError(f"Invalid timestamp type: {type(timestamp)}")
    return utc(timestamp).replace(tzinfo=None).isoformat() + "Z"


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
