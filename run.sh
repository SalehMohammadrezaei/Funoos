#!/usr/bin/env bash
# Launch Funoos. Uses the local .venv if install.sh created one.
cd "$(dirname "$0")"
PY=python3
[ -x .venv/bin/python ] && PY=.venv/bin/python
exec "$PY" funoos_app.py
