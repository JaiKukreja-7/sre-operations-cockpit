#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -x .venv/bin/python ]]; then
  echo "Create the Python 3.11 virtual environment first; see README.md." >&2
  exit 1
fi
echo "Dashboard: http://127.0.0.1:8000 (open in your browser after startup)."
echo "The checked-in dashboard bundle requires no Node process. Press Ctrl+C to stop."
exec .venv/bin/python -m cockpit.launch
