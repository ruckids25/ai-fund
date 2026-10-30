#!/usr/bin/env bash
# cron: 0 0 * * 2-6 (UTC = 07:00 TH อ–ส) — ไม่เกี่ยวกับการเทรด ล้มแล้วแจ้งเตือนอย่างเดียว
set -u
cd "$(dirname "$0")/.."
mkdir -p logs
LOG="logs/label_$(date -u +%Y%m).log"
{
  echo "=== $(date -u +%FT%TZ)"
  flock -n /tmp/ai-fund-label.lock envs/data/bin/python -W ignore scripts/label_outcomes.py
  rc=$?
  echo "exit=$rc"
} >>"$LOG" 2>&1
if [ "${rc:-1}" -ne 0 ]; then
  .venv/bin/python -m core.notify "⚠️ ai-fund: เก็บผลหลังการตัดสินใจล้มเหลว (รหัส $rc) — ดู $LOG บน VPS" >>"$LOG" 2>&1
fi
