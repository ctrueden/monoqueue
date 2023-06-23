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
log.is_critical = lambda: log.isEnabledFor(logging.CRITICAL)
log.is_error = lambda: log.isEnabledFor(logging.ERROR)
log.is_warning = lambda: log.isEnabledFor(logging.WARNING)
log.is_info = lambda: log.isEnabledFor(logging.INFO)
log.is_debug = lambda: log.isEnabledFor(logging.DEBUG)

def setup_logging():
    level = (
        logging.DEBUG
        if os.environ.get("DEBUG")
        else logging.INFO
    )
    logging.basicConfig(level=level)
