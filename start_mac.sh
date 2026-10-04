#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -x .venv/bin/python ]]; then
  echo "Create the Python 3.11 virtual environment first; see README.md." >&2
  exit 1
fi
exec .venv/bin/python -m cockpit.launch
