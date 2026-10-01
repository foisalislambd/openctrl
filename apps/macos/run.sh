#!/bin/sh
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
.venv/bin/python -m pip install -q -r requirements.txt
exec .venv/bin/python main.py
