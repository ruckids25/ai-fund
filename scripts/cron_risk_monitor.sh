#!/usr/bin/env bash
# cron: */5 * * * * — risk_monitor.py แจ้ง Telegram เองเมื่อถึง limit หรืออ่านบัญชีไม่ได้
set -u
cd "$(dirname "$0")/.."
mkdir -p logs
LOG="logs/risk_monitor_$(date -u +%Y%m).log"
{
  echo "=== $(date -u +%FT%TZ)"
  flock -n /tmp/ai-fund-risk-monitor.lock .venv/bin/python risk_monitor.py
  echo "exit=$?"
} >>"$LOG" 2>&1
