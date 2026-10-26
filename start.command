#!/bin/zsh
set -eu
cd "$(dirname "$0")"
if [[ ! -x .venv/bin/python ]]; then
  print 'Create a Python 3.11+ virtual environment and install the project first:'
  print "python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'"
  read '?Press Return to close…'
  exit 1
fi
exec .venv/bin/python -m runorwalk.server --open
