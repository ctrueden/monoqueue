#!/usr/bin/env python
#
# This is free and unencumbered software released into the public domain.
# See the UNLICENSE file for details.
#
# ------------------------------------------------------------------------
# __main__.py
# ------------------------------------------------------------------------

"""
Monoqueue main entry point.
"""

import sys
from . import cli


if __name__ == "__main__":
    sys.exit(cli.main())
