#!/usr/bin/env bash
# cron: 30 23 * * 1-5 และ 0 14 * * 1-5 (UTC) — อ่าน Alpaca อย่างเดียว ล้มแล้วไม่กระทบการเทรด
set -u
cd "$(dirname "$0")/.."
mkdir -p logs
LOG="logs/reconcile_$(date -u +%Y%m).log"
{
  echo "=== $(date -u +%FT%TZ)"
  flock -n /tmp/ai-fund-reconcile.lock .venv/bin/python scripts/reconcile_orders.py
  rc=$?
  echo "exit=$rc"
} >>"$LOG" 2>&1
if [ "${rc:-1}" -ne 0 ]; then
  .venv/bin/python -m core.notify "⚠️ ai-fund: อัปเดตผลออเดอร์ล้มเหลว (รหัส $rc) — ดู $LOG บน VPS" >>"$LOG" 2>&1
fi
