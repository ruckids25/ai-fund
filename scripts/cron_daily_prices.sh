#!/usr/bin/env bash
# cron: 0 23 * * 1-5 (UTC = 06:00 TH) — หลังตลาด US ปิดทั้งช่วง DST และไม่ DST
# ถ้า script ล้ม ส่งแจ้งเตือนแยก เพื่อไม่ให้ "เงียบ" แล้วไม่รู้ว่าระบบตาย
set -u
cd "$(dirname "$0")/.."
mkdir -p logs
LOG="logs/daily_prices_$(date -u +%Y%m).log"
{
  echo "=== $(date -u +%FT%TZ)"
  flock -n /tmp/ai-fund-daily-prices.lock envs/data/bin/python -W ignore scripts/daily_prices.py
  rc=$?
  echo "exit=$rc"
} >>"$LOG" 2>&1
if [ "${rc:-1}" -ne 0 ]; then
  .venv/bin/python -m core.notify "⚠️ ai-fund: daily_prices exit=$rc — ดู $LOG บน VPS" >>"$LOG" 2>&1
fi
