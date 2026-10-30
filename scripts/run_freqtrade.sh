#!/usr/bin/env bash
# freqtrade dry-run ของ TrendEma4h — ใช้ทดสอบระบบเท่านั้น (backtest ไม่ผ่าน, ไม่นับเป็น paper ของ Phase 5)
# ไม่ใช้ key ของ OKX: config มี dry_run true และ key ว่าง จึงส่งออเดอร์จริงไม่ได้
set -eu
cd "$(dirname "$0")/.."
get() { grep -E "^$1=" .env | head -1 | cut -d= -f2-; }
export FREQTRADE__TELEGRAM__ENABLED=true
FREQTRADE__TELEGRAM__TOKEN="$(get TG_FT_TOKEN)"
FREQTRADE__TELEGRAM__CHAT_ID="$(get TG_CHAT_ID)"
export FREQTRADE__TELEGRAM__TOKEN FREQTRADE__TELEGRAM__CHAT_ID
U=crypto/freqtrade/user_data
exec envs/freqtrade/bin/freqtrade trade --userdir "$U" -c "$U/config.json" \
  --strategy TrendEma4h --db-url sqlite:///data/freqtrade_dry.sqlite
