#!/usr/bin/env python
#
# This is free and unencumbered software released into the public domain.
# See the UNLICENSE file for details.
#
# ------------------------------------------------------------------------
# log.py
# ------------------------------------------------------------------------

"""
The monoqueue logger.
"""

import logging, os

log = logging.getLogger("monoqueue")

def setup_logging():
    level = (
        logging.DEBUG
        if os.environ.get("DEBUG")
        else logging.INFO
    )
    logging.basicConfig(level=level)
