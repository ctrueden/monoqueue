#!/bin/sh

# Executes the unit tests.
#
# Usage examples:
#   bin/test.sh
#   bin/test.sh tests/test_parse.py

dir=$(dirname "$0")
cd "$dir/.."

if [ $# -gt 0 ]
then
  uv run python -m unittest -v $@
else
  uv run python -m unittest -v tests/*.py
fi
