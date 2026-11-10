#!/bin/bash
# Start gleaner. Leave this Terminal window open; Ctrl+C stops it.
cd "$(dirname "$0")"
exec .venv/bin/python gleaner.py "$@"
