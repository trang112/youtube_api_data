#!/usr/bin/env bash
set -euo pipefail

cd "/home/trang/Documents/jde/Big Project 1" || exit 1
mkdir -p logs

echo "=== Run started at $(date '+%Y-%m-%d %H:%M:%S') ===" >> logs/cron.log

.venv/bin/python3 main.py >> logs/cron.log 2>&1

echo "=== Run finished with code $? ===" >> logs/cron.log