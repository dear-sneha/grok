#!/bin/bash
set -e

# Clear any old browser profile locks
rm -rf /app/browser_profile/* 2>/dev/null || true

# Run with xvfb-run
exec xvfb-run -a python grok_auto.py --upload-drive
