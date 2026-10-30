#!/usr/bin/env bash
# cron: 15 0 * * 2-6 (UTC = 07:15 TH อ–ส) — เขียน Sheet จาก ledger ทางเดียว ล้มแล้วแจ้งเตือนอย่างเดียว
set -u
cd "$(dirname "$0")/.."
mkdir -p logs
LOG="logs/sheet_sync_$(date -u +%Y%m).log"
{
  echo "=== $(date -u +%FT%TZ)"
  flock -n /tmp/ai-fund-sheet.lock envs/data/bin/python -W ignore scripts/sheet_sync.py
  rc=$?
  echo "exit=$rc"
} >>"$LOG" 2>&1
if [ "${rc:-1}" -ne 0 ]; then
  .venv/bin/python -m core.notify "⚠️ ai-fund: อัปเดต Google Sheet ล้มเหลว (รหัส $rc) — ดู $LOG บน VPS" >>"$LOG" 2>&1
fi
