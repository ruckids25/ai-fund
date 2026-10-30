#!/usr/bin/env bash
# cron: 5 23 * * 1-5 (UTC = 06:05 TH) — หลังตลาด US ปิด และนอกช่วงพีคของ DeepSeek
# fund.py รายงาน Telegram เอง; script นี้แจ้งเฉพาะกรณี process ล้ม
set -u
cd "$(dirname "$0")/.."
mkdir -p logs
LOG="logs/fund_$(date -u +%Y%m).log"
{
  echo "=== $(date -u +%FT%TZ)"
  flock -n /tmp/ai-fund-fund.lock envs/ta/bin/python -W ignore fund.py
  rc=$?
  echo "exit=$rc"
} >>"$LOG" 2>&1
if [ "${rc:-1}" -ne 0 ]; then
  .venv/bin/python -m core.notify "⚠️ ai-fund: รอบวิเคราะห์หุ้นล้มเหลว (รหัส $rc) — ดู $LOG บน VPS" >>"$LOG" 2>&1
fi
