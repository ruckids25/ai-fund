#!/usr/bin/env bash
# รันบน VPS: bash scripts/check_vps.sh — พิมพ์สเปกที่ต้องใช้ตัดสินว่าพอสำหรับ Kronos-small + freqtrade
# ไม่อ่าน .env และไม่พิมพ์ secret ใดๆ
set -u

echo "== OS ==";      (. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME") || uname -a
echo "== Arch ==";    uname -m
echo "== CPU ==";     nproc; grep -m1 'model name' /proc/cpuinfo 2>/dev/null | cut -d: -f2
grep -qw avx2 /proc/cpuinfo 2>/dev/null && echo "AVX2: yes" || echo "AVX2: no"
echo "== RAM ==";     free -h 2>/dev/null | sed -n '1,3p'
echo "== Disk ==";    df -h / | tail -1
echo "== GPU ==";     (command -v nvidia-smi >/dev/null && nvidia-smi --query-gpu=name,memory.total --format=csv,noheader) || echo "none"
echo "== Docker ==";  (docker --version && docker compose version) 2>/dev/null || echo "not installed"
echo "== Python ==";  for p in python3 python3.10 python3.11 python3.12; do command -v $p >/dev/null && echo "$p: $($p --version 2>&1)"; done
echo "== uv ==";      command -v uv >/dev/null && uv --version || echo "not installed"
echo "== git ==";     git --version 2>/dev/null || echo "not installed"
echo "== Time ==";    timedatectl 2>/dev/null | grep -E 'Time zone|synchronized' || date -u
echo "== Load ==";    uptime
echo "== Other bots (PRS) — แค่ดูว่ามี process อะไรกิน RAM อยู่ =="
ps -eo pid,rss,comm --sort=-rss 2>/dev/null | head -8

cat <<'TXT'

== เกณฑ์ (Kronos-small ~25M params, CPU) ==
- RAM ว่าง >= 2 GB (torch CPU + model + 100 paths) ; freqtrade ~300-500 MB ; รวมแนะนำ >= 4 GB total
- Disk ว่าง >= 10 GB (torch CPU ~1-2 GB, venvs, docker images, ข้อมูล)
- CPU >= 2 cores ; AVX2 ช่วยให้ torch เร็วขึ้นมาก
- เวลา sync (NTP) = yes จำเป็นสำหรับ timestamp ใน ledger / exchange
TXT
