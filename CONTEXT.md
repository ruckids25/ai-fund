# AI Fund — Project Context

> อ่านไฟล์นี้ก่อนเริ่มทุก session ใน Claude Code และอัปเดตส่วน "สถานะล่าสุด" ก่อนจบทุก session

## เป้าหมาย
สร้างระบบเทรดอัตโนมัติแบบ "AI hedge fund" ตามโครง 4 desk (Research → Committee → Execution → Risk)
ครอบคลุมทั้ง **หุ้น US** และ **crypto** โดยวัดความสำเร็จจาก:
1. ระบบรันเองได้ทุกวันโดยไม่ต้องกดมือ
2. Backtest และ paper trade ต่อเนื่อง มีบันทึกผลที่ตรวจย้อนได้
3. เข้าใจ logic ของบอททุกชั้น ไม่ใช่ black box

## ขอบเขตและข้อตกลง
- **งบขาดทุนรวม:** 15,000 THB (เป็นเพดานขาดทุน ไม่ใช่ทุนทั้งหมด) ดูกฎใน `RISK_RULES.md`
- **Leverage สูงสุด:** 5x (เฉพาะ crypto perps, isolated margin)
- **เริ่มใหม่ทั้งหมด** ไม่ใช้ strategy หรือ indicator เดิม
- **แยกขาดจาก PRS bot:** คนละ repo, คนละ OKX sub-account, คนละ API key, คนละ Telegram bot ห้ามแชร์อะไรกัน
- **รันบน VPS** ที่มีอยู่แล้ว
- ทุกอย่างเริ่มที่ **paper / dry-run** เท่านั้น

## สถาปัตยกรรม (4 Desks)

| Desk | หน้าที่ | หุ้น US | Crypto |
|---|---|---|---|
| Research | ดูอะไร | OpenBB, daily_stock_analysis, Kronos | ccxt (OKX), Kronos |
| Committee | เทรดอะไร | TradingAgents (+ ai-hedge-fund เทียบ) | strategy ใน freqtrade |
| Risk | เท่าไหร่ / หยุดเมื่อไหร่ | `core/risk_gate.py` (deterministic, ใช้ร่วมกัน) | `core/risk_gate.py` |
| Execution | ส่งออเดอร์ | Alpaca paper (bracket order) | freqtrade dry-run บน OKX |

**หลักการสำคัญ:** LLM เสนอได้ แต่ไม่มีสิทธิ์ส่งออเดอร์เอง ทุกออเดอร์ต้องผ่าน `risk_gate.py` ซึ่งเป็นโค้ดธรรมดา ไม่มี LLM อยู่ข้างใน

### ลำดับการทำงานรายวัน (หุ้น)
1. OpenBB ดึง candle รายวัน
2. Kronos สร้าง 100 paths → ผ่านเกณฑ์เท่านั้นจึงไปต่อ (cheap filter)
3. TradingAgents ถกเถียงเฉพาะตัวที่ผ่าน (expensive filter)
4. risk_gate คำนวณ size, ตรวจ daily/total loss limit
5. Alpaca paper ส่ง bracket order
6. Telegram ส่งสรุป + บันทึกลง ledger

## สิ่งที่ตัดออกหรือเลื่อนไว้
- **hummingbot (market making):** ตัดออก ทุนเล็กรับ inventory risk ไม่ไหว
- **Funding-rate arbitrage:** ตัดออก fee กิน spread หมด และต้องวางเงินสองกระดาน
- **RD-Agent:** เลื่อนไป Phase 6 ต้องรันบนเครื่องแยกที่ไม่มี credential จริง (มันเขียนและรันโค้ดเอง) ห้ามรันบน VPS ตัวเดียวกับบอท
- **NautilusTrader:** เลื่อนไป Phase 6 ยังเป็น v2 release candidate

## โครงสร้าง Repo
```
ai-fund/
├── CONTEXT.md / RISK_RULES.md / WORKFLOW.md / .env.example / pyproject.toml
├── config/
│   ├── watchlist.yaml        # รายชื่อหุ้น + คู่ crypto
│   └── risk.yaml             # ตัวเลขจาก RISK_RULES.md (ไฟล์เดียวที่โค้ดอ่าน)
├── core/
│   ├── data.py               # OpenBB + ccxt wrapper
│   ├── risk_gate.py          # sizing, limits, kill switch
│   ├── ledger.py             # บันทึกทุก decision + ผล (SQLite)
│   └── notify.py             # Telegram
├── desks/
│   ├── research/kronos_filter.py
│   └── committee/ta_committee.py
├── crypto/freqtrade/user_data/   # config + strategies
├── vendor/                   # clone ของ Kronos, TradingAgents (gitignore)
├── backtests/                # ผล backtest ทุกครั้ง
├── journal/                  # บันทึกรายสัปดาห์: ลองอะไร ได้อะไร
├── scripts/                  # check_vps.sh, ops scripts
├── tests/                    # pytest
└── fund.py                   # orchestrator รายวัน (หุ้น)
```
แต่ละ component ใช้ **venv หรือ Docker แยกกัน** (torch, freqtrade และ TradingAgents มี dependency ชนกันได้)

## แผนงาน (8 สัปดาห์)

| Phase | สัปดาห์ | งาน | เกณฑ์ผ่าน |
|---|---|---|---|
| 0 | 1 | VPS, repo, secrets, Telegram bot, OKX sub-account, Alpaca paper, ตั้ง spend limit ที่ Anthropic | `.env` ครบ, ส่งข้อความ Telegram ทดสอบได้ |
| 1 | 1–2 | Data layer (OpenBB + ccxt) + fork daily_stock_analysis ลง Telegram | morning note มาทุกวันทำการ |
| 2 | 2–3 | Kronos filter + **ทดสอบย้อนหลังว่า filter มีความแม่นจริงไหม** | รู้ hit rate ของเกณฑ์ 70% บนข้อมูลอดีต |
| 3 | 3–4 | TradingAgents backtest grid (ใช้ Sonnet ทั้งคู่ก่อนเพื่อคุมค่าใช้จ่าย) | รู้ค่า API ต่อรอบ + ผล alpha |
| 4 | 4–5 | risk_gate + ledger + fund.py บน Alpaca paper / freqtrade strategy แรก + lookahead-analysis | รันครบ loop โดยไม่ต้องแตะมือ 5 วัน |
| 5 | 5–8 | Paper run 30 วัน + journal รายสัปดาห์ | ผ่านเกณฑ์ go-live ใน RISK_RULES.md |
| 6 | หลังจากนั้น | RD-Agent (เครื่องแยก), NautilusTrader, ai-hedge-fund เทียบผล | ตัดสินใจทีละตัว |

## เรื่องที่ต้องตรวจสอบ
- [ ] Alpaca เปิดบัญชี **live** ให้ผู้พำนักในไทยได้หรือไม่ (paper ใช้ได้แน่นอน)
- [x] สเปก VPS (RAM/CPU) พอสำหรับ Kronos-small บน CPU หรือไม่ → **ไม่พอ** (2026-10-28: 45.76.159.133 Ubuntu 24.04, 1 vCPU EPYC AVX2, RAM 955Mi ว่าง ~540Mi + swap 2.3G, disk ว่าง 16G, ไม่มี Docker/uv, UTC + NTP sync ok, มี PRS bot รันอยู่) — พอสำหรับ Phase 1 (cron วันละครั้ง) แต่ไม่พอ Kronos + freqtrade
- [ ] TradingAgents รองรับ crypto ได้ดีแค่ไหน ถ้าไม่ดี committee ฝั่ง crypto ใช้ strategy rule-based แทน
- [ ] อัตราแลกเปลี่ยน THB/USD สำหรับแปลงงบใน `risk.yaml`

## Log การตัดสินใจ
- 2026-10-27: เลือกตาม stack ในบทความ "10 GitHub repos" ครอบคลุมหุ้น + crypto, เริ่มใหม่ไม่ใช้ strategy เดิม, แยกจาก PRS bot, งบขาดทุน 15K THB, leverage ≤ 5x, ตัด hummingbot และ funding arb
- 2026-10-28: พัฒนาบน Mac → private GitHub repo → `git pull` บน VPS (แทนการเขียนบน VPS ตรงๆ), สเปก VPS ให้ตรวจตอน Phase 0, ทุนบัญชีบอท = 15,000 THB (เท่างบขาดทุน — OKX ฝากไม่เกินนี้, Alpaca paper ตั้ง equity เทียบเท่า), strategy crypto ตัวแรก: Claude เสนอ 2–3 แบบให้เลือกก่อน Phase 4, THB/USD: fix ใน risk.yaml อัปเดตรายสัปดาห์ (default จนกว่าจะเปลี่ยน)
- 2026-10-28: เช่า VPS ใหม่แยกจาก PRS bot (VPS เดิม 1 vCPU/1GB ไม่พอ Kronos + freqtrade และแยกขาดจาก PRS bot ทั้งเครื่อง + IP whitelist OKX ไม่ปนกัน)
- 2026-10-28: แก้ RISK_RULES ข้อ 2 และ 7 (ยังไม่มี position เปิด) — เหตุผล: ทุน 15K THB + กฎ margin 20% ทำให้หุ้นแบบเงินสดเสี่ยงได้แค่ ~120 THB/เทรด และเปิด 3 ตัวไม่ได้ จึงแยกทุนหุ้นใน paper = $3,000 (ค่าเริ่มต้น ต้องเท่าทุนจริงที่พร้อมใส่), cap หุ้น 33%/ตัว, งบขาดทุน 15K ยังใช้ร่วมกัน, เพิ่มเกณฑ์ ≥30 เทรด/desk และต้องมีบัญชีหุ้นจริงก่อน go-live ฝั่งหุ้น

## สถานะล่าสุด
**2026-10-30 — Trade journal Part A: reconcile ออเดอร์ Alpaca → ledger (รอผู้ใช้ตั้ง cron และตรวจเทียบ dashboard)**
- `scripts/reconcile_orders.py` อ่าน Alpaca อย่างเดียว อัปเดต fill, exit, PnL, R ใน `orders`; คอลัมน์ใหม่เพิ่มอัตโนมัติผ่าน `ADDED_COLUMNS` ใน ledger (เพิ่ม `fx_usdthb` จาก spec เพื่อเก็บ fx ของ pnl_thb)
- `exit_reason` close_all vs manual: แยกจากข้อความ hard stop ใน halt flag; `fees_usd` ยังว่าง (paper ไม่คิดค่าคอม)
- `realized_pnl_thb()` ไม่ถูกใช้ในการตัดสินใจเทรด risk_monitor คำนวณจาก equity จึงไม่นับซ้ำ
- **ยังไม่ได้พิสูจน์กับออเดอร์จริง:** ทดสอบด้วยข้อมูลจำลอง และเรียก API จริงได้แต่ยังไม่มีไม้ รูปแบบข้อมูลของ leg ที่ fill และ activities ต้องเทียบเมื่อมีไม้แรก
- Part B, C ยังไม่เริ่ม (`backtests`/spec อยู่ในแชต ควรเก็บเป็นไฟล์เมื่อทำต่อ)

**2026-10-30 — Phase 4: เชื่อม freqtrade dry-run กับ risk_gate + risk_monitor (A ใช้ทดสอบระบบเท่านั้น)**
- ข้าม venv ด้วยไฟล์ snapshot `core/risk_state.py`: freqtrade เขียน `data/crypto_pnl.json` ทุกนาที, risk_monitor รวม PnL + เขียน `data/risk_state.json` ทุก 5 นาที; ก่อนทุก entry freqtrade เรียก `approve_crypto_entry` — snapshot หายหรือเกิน 15 นาที = ปฏิเสธ; hard stop ปิดฝั่ง crypto ผ่าน `custom_exit`
- PnL + จำนวน position ใน fund.py และ risk_monitor นับ crypto แล้ว; PnL รายวันฝั่ง crypto = realized วันนี้ + unrealized ตอนนี้ (ประมาณ)
- ลองรันบน Mac ~2 นาที: RUNNING ไม่มี error, เขียน crypto_pnl ได้, backtest ผลเดิม (218 เทรด) — **ยังไม่เคยเห็น entry จริงผ่าน gate ใน dry-run** (A เทรด ~3.8 ครั้ง/เดือน)
- service `ai-fund-freqtrade` รันบน VPS ตั้งแต่ 11:39 UTC (ผู้ใช้ติดตั้ง + ยืนยันว่า @AI_2trade_bot เป็นของ ai-fund), snapshot ไหลครบ
- Kill switch: `fund.py --halt` ทดสอบผ่าน 2026-10-30 (ปฏิเสธทั้งหุ้นและ crypto, เคลียร์แล้ว); Telegram `/stopentry` ผู้ใช้ทดสอบผ่าน (หลังใช้ต้องสั่ง `/reload_config` เท่านั้น `/start` ไม่คืน entry); ค้างทดสอบ `/forceexit all` เมื่อมีเทรด และปิด API key ด้วยมือ
- `scripts/backup_ledger.py` รันมือบน VPS ผ่าน เก็บ 14 วันใน `data/backups/` (เครื่องเดียวกัน กันไฟล์เสียเท่านั้น); รอผู้ใช้ตั้ง cron 23:59 UTC
- ห้ามนับ dry-run ของ A เป็น paper Phase 5 และห้าม live

**2026-10-30 — Phase 4 crypto: strategy B (สวนกลับ 1h) ไม่ผ่านเช่นกัน**
- PF 0.67, DD 17,090 THB, ถึง hard stop ในการจำลอง — ดู `backtests/crypto_meanrev1h_20261030/conclusion.md`; ลองแล้ว 2 แบบ ตกลงไว้ว่าลองไม่เกินอีก 1 แบบ
- สถานะรวม: ยังไม่มีสัญญาณใดพิสูจน์ได้ว่ามี edge ทั้งหุ้น (committee) และ crypto (A, B)

**2026-10-30 — Phase 4 crypto: strategy A (ตามเทรนด์ 4h) ไม่ผ่าน → ยังไม่มี strategy crypto**
- เกณฑ์กำหนดและ commit ก่อนเห็นผล; PF 0.87, ขาดทุนทั้งสองครึ่ง, DD 8,359 THB, 3.8 เทรด/เดือน — ดู `backtests/crypto_trend4h_20261030/conclusion.md`
- `envs/freqtrade` (2026.10) บน Mac เท่านั้น, `crypto/freqtrade/user_data/{config.json,strategies/TrendEma4h.py}`; ขนาดไม้ + leverage อ่านจาก risk_gate; ยังไม่ได้เรียก `evaluate_order` ใน callback
- OKX ให้ประวัติ funding แค่ ~3 เดือน: backtest ต้องเผื่อเอง; dry-run ใช้ข้อมูลสาธารณะได้ ยังไม่ต้องมี OKX sub-account
- **ค้างตัดสินใจ:** ทดสอบ strategy ถัดไป หรือใช้ A แค่ทดสอบระบบใน dry-run; ทุกครั้งที่ลองใหม่ต้องตั้งเกณฑ์ล่วงหน้า และยิ่งลองหลายแบบยิ่งเสี่ยงได้ผลดีจากความบังเอิญ

**2026-10-30 — Phase 4: `risk_monitor.py` รันบน VPS ทุก 5 นาที (ลูป C) ตั้งแต่ 11:10 UTC**
- daily = แจ้งเตือน, soft = halt ค้าง, hard = halt + ปิดทุก position; แจ้งครั้งเดียวต่อเหตุการณ์ (ส่งไม่สำเร็จจะลองใหม่), อ่านบัญชีไม่ได้ 3 รอบติดแจ้งเตือน, ส่งสรุปวันละครั้งเพื่อยืนยันว่ายังทำงาน, บันทึก `daily_pnl` ทุกรอบ
- ใช้ cron แทน systemd timer ตาม WORKFLOW เพื่อให้เหมือนงานอื่นบน VPS; ยังนับเฉพาะ PnL หุ้นจนกว่าจะมี freqtrade
- ไม่ได้ตรวจว่าทุก position มี stop อยู่ที่ broker จริง → ควรเพิ่มเมื่อมี position จริงให้ดูรูปแบบข้อมูลของ Alpaca
- ค้าง Phase 4: freqtrade + เลือก strategy crypto + OKX sub-account, lookahead-analysis, backup ledger, ทดสอบ kill switch

**2026-10-30 — Phase 4: `fund.py` รันเองบน VPS (Alpaca paper) — ผู้ใช้ตั้ง cron แล้ว**
- cron (UTC): `5 23 * * 1-5 scripts/cron_fund.sh` = 06:05 TH อ–ส, รันแรก 31 ต.ค. เช้า (TH), log ที่ `logs/fund_YYYYMM.log`; `envs/ta` บน VPS แล้ว (TradingAgents c454491, dependency ตรงกับ Mac)
- `TG_TOKEN`, `TG_FT_TOKEN` และ Alpaca paper key หมุนใหม่แล้ว 2026-10-30 ทั้ง Mac + VPS, Telegram/Alpaca ทดสอบผ่านทั้งสองเครื่อง; บอทคือ @AI_Fund_Alerts_bot
- dry-run NVDA: Mac (วันที่ 10-30 ตลาดยังไม่ปิด จากบั๊กที่แก้แล้ว) = Overweight, VPS (10-29) = Underweight → ต้องดูความนิ่งของ committee ตอน paper
- 300 บาท ≈ $8.90 ต่อเทรด + ซื้อหุ้นเต็มตัว: stop เกิน ~$8.90 ต่อหุ้นถูกปฏิเสธ; สัญญาณซื้อจาก grid ผ่าน gate 12/15 ตัว
- ค้าง Phase 4: `risk_monitor` (ตอนนี้เช็ก limits แค่วันละครั้งและ PnL หุ้นเท่านั้น), freqtrade + เสนอ strategy crypto + OKX sub-account, lookahead-analysis, backup ledger; เกณฑ์ผ่าน 5 วันติดต้องนับเมื่อครบลูปรวม kill switch

**2026-10-30 — Phase 4: `fund.py` + Alpaca paper (ยังไม่ได้ตั้ง schedule)**
- `core/alpaca.py`: stdlib, URL fix ที่ paper; entry = limit GTC + stop ที่ broker เพราะขา stop ของ bracket แบบ DAY หมดอายุตอนตลาดปิด; fund.py ยกเลิก entry ที่ค้างในรอบถัดไป
- `fund.py`: ปฏิเสธถ้าตลาดเปิด, อ่านบัญชีไม่ได้ = หยุด, เช็ก limits ก่อนจ่ายค่า LLM, ข้ามตัวที่ถืออยู่, ≤5 ตัว/วัน, หยุด committee เมื่อค่า API ถึงเพดาน, ออเดอร์ใหม่นับรวมเพดาน 3 ตัว; committee "sell" ไม่เปิดอะไร (long-only)
- ทดสอบ: bracket NVDA ไกลตลาด (limit $5) Alpaca paper รับ แล้วยกเลิกทันที ไม่มี position ค้าง
- **ข้อจำกัด:** บัญชี paper มี equity $100,000 ไม่ใช่ $3,000 ตาม RISK_RULES → ตั้ง `paper_baseline_usd: 100000` และ gate คุมขนาดด้วย capital_usd ถ้า reset บัญชีต้องแก้ค่านี้; PnL ยังนับเฉพาะหุ้น (รอ risk_monitor รวม crypto)
- fx.usdthb ตรวจแล้ว 33.7 (Yahoo 2026-10-30) ไม่มี position เปิด
- `.env` ทั้ง Mac และ VPS แก้ล่าสุด 10:57 ของวันนี้ — **ยังไม่ยืนยันว่า Telegram/Alpaca key ที่ใช้อยู่เป็นชุดที่หมุนใหม่แล้ว**
- ค้าง Phase 4: ลง envs/ta บน VPS + schedule, freqtrade dry-run, risk_monitor, lookahead-analysis, backup ledger

**2026-10-30 — Phase 4 เริ่ม: `core/risk_gate.py` เสร็จ (ยังไม่มีการส่งออเดอร์)**
- ตัดสินใจทำ Phase 4 ก่อนทดสอบ committee เพิ่ม; committee ใช้ใน paper เท่านั้น ยังไม่มีหลักฐาน edge พอสำหรับเงินจริง
- `evaluate_order()` คือทางเข้าเดียวของทุกออเดอร์: ตรวจ halt/limits/stop แล้วคำนวณ size; ข้อมูลผิดหรือไม่มี stop = reject; soft/hard stop เขียน halt flag ค้างไว้จนคนเคลียร์ (PnL ฟื้นก็ไม่เปิดเอง), daily stop ไม่ค้าง, hard stop คืน `close_all` ให้ผู้เรียกปิดทุก position
- เพิ่ม `desks.crypto.maint_margin_pct: 0.005` ใน risk.yaml (ไม่มี position เปิด) เพื่อประมาณราคา liq — เป็นค่าประมาณ ต้องเทียบกับ OKX จริง
- tests/test_risk_gate.py 44 ผ่าน รวมค่าขอบทุกกฎ
- ยังไม่มีใครเรียก risk_gate; `AccountState` ต้องมาจาก risk_monitor/broker (ยังไม่ได้ทำ)
- **ก่อนทำต่อ (ผู้ใช้):** revoke/สร้าง Telegram + Alpaca key ใหม่, ตรวจ `fx.usdthb`, OKX sub-account (whitelist IP ของ VPS ใหม่)

**2026-10-30 — Phase 3: grid DeepSeek 40 cell จบ → ยังไม่เห็น edge (buy +0.14% vs ถือทุก cell +0.55% ต่อ 5 sessions)**
- รายละเอียด + ข้อจำกัดที่ `backtests/ta_20261030_deepseek/conclusion.md`; buy − sell = −0.75% (t ≈ −0.68) ไม่มีนัย ตัวอย่างเล็ก; ค่าจริง $6.41 ≈ $0.16/cell → งบ $30/เดือน ≈ 9 ตัว/วัน
- **ค้างตัดสินใจ:** จะไปต่อ Phase 4 ด้วย committee นี้ไหม หรือทดสอบเพิ่มก่อน (ยังไม่ตัดสิน)

**2026-10-30 — Phase 3: เปลี่ยน committee เป็น DeepSeek + รัน backtest grid 40 cell**
- Gemini free tier ไม่พอ: gemini-3.8-flash ได้แค่ 20 requests/วัน → grid แรก (`backtests/ta_20261030_gemini/`) ได้ 5 cell (Overweight ทั้งหมด วันที่ 2026-08-31) ที่เหลือ 429 quota → เก็บไว้แยก ไม่ใช้สรุปผล
- เปลี่ยน `config/committee.yaml` เป็น DeepSeek (เติมเงิน prepaid $20, key ใน `DEEPSEEK_API_KEY`): quick = deepseek-flash, deep = deepseek-v4-pro; ราคาใน yaml เป็นราคา peak cache-miss (upper bound) — off-peak ลดครึ่ง, peak = 13:00–16:00 และ 08:00–11:00 TH จ–ศ
- Anthropic ยังเติมเครดิตไม่ได้ → ถ้ากลับไปใช้ Claude ต้องตั้ง `temperature: null` (Messages API ปฏิเสธ temperature ตั้งแต่ 2026-10-21)
- `backtests/ta_committee_backtest.py run|report --out <dir>`: หุ้น NVDA/AAPL/MSFT/JPM/XOM × 8 วันจันทร์ 2026-08-31 → 10-19, วัด ret 5 sessions เทียบ buy-and-hold ทุก cell + ผล stop/target ใน 10 sessions; resume ได้จาก decisions.csv
- grid DeepSeek เริ่ม ~10:50 TH ที่ `backtests/ta_20261030_deepseek/` (รันบน Mac ด้วย caffeinate) — จบ ~17:15, ไม่มี error, เฉลี่ย ~9 นาที/cell
- rating ทั้งหมด: Underweight 20, Overweight 15, Hold 5 (ไม่มี Buy/Sell เต็มตัว) — ไม่เอียงขาขึ้นแบบ Gemini
- ข้อจำกัดที่รู้: LLM อาจรู้ราคาช่วงนี้จาก training data (cutoff ไม่แน่ชัด), Yahoo ให้ข่าวย้อนหลังน้อย, ไม่มี FRED key
- **ถัดไป (ถ้าไปต่อ):** ลง `envs/ta` บน VPS, ส่ง Kronos (p_up/q10/q90) เข้า committee, เลือกเกณฑ์หุ้นเข้า committee (≤5/วัน), เทียบการแบ่งโมเดล

**2026-10-30 — Phase 3 เริ่ม: TradingAgents committee ใช้ Gemini free tier (ยังไม่มีเครดิต Anthropic)**
- `vendor/TradingAgents` v0.7.1 (c454491), `envs/ta` (Mac เท่านั้น ยังไม่ได้ลง VPS); key อยู่ใน `GOOGLE_API_KEY`
- `config/committee.yaml`: quick = gemini-3.5-flash-lite, deep = gemini-3.8-flash (Pro ไม่อยู่ใน free tier), debate 1 รอบ
- `desks/committee/ta_committee.py`: คืน `{ticker, action, entry, stop, target, confidence, rationale, cost_usd}` + rating/tokens; บันทึก token ต่อโมเดลลง `api_costs`, decision ลง `decisions` (stage=committee); confidence มาจาก rating แบบกำหนดเอง ไม่ได้ calibrate
- ทดสอบ NVDA 2026-10-29: Overweight → buy, entry 215.38 / stop 198 / target 240, 211 วินาที, quick 105K in + 9K out (16 calls), deep 4.6K in + 2.2K out (2 calls)
- ประมาณค่า Claude จาก token เดียวกัน (โทเคนไนเซอร์ต่างกัน ตัวเลขหยาบ): Haiku 5.5 + Sonnet 5.5 ≈ $0.05/รอบ, Sonnet ทั้งหมด ≈ $0.33/รอบ
- ไม่มี FRED_API_KEY → ข้อมูล macro ถูกข้าม (optional); Kronos ยังไม่ได้ส่งเข้า committee

**2026-10-30 — Phase 2 จบ: Kronos ไม่ผ่านเกณฑ์ด่านกรอง → ใช้เป็นข้อมูลให้ committee**
- walk-forward 2,332 forecasts (หุ้น 30 ตัว 1d, BTC/ETH 1d+4h) 2025-09 → 2026-10: `p_up ≥ 0.70` hit rate ไม่ต่างจาก base อย่างมีนัย (หุ้น 53.9% vs 52.4%), calibration แบน, IC ≈ 0 — รายละเอียด `backtests/kronos_20261029/conclusion.md`
- ผลต่อ pipeline: Phase 3 ไม่ใช้ Kronos ตัดหุ้นทิ้ง; ส่ง p_up/q10/q90 ให้ TradingAgents เป็น context และเลือกหุ้นเข้า committee ด้วยเกณฑ์อื่น (ภายใต้เพดาน 5 ตัว/วัน)
- ความกว้าง q90−q10 พอบอกความผันผวนได้ (Spearman กับ |ret| หุ้น 0.21) — ถ้าจะใช้ตั้ง stop ต้องเทียบกับ ATR ก่อน

**2026-10-29 — Phase 2 เริ่ม: Kronos filter + walk-forward backtest (รันบน Mac, MPS)**
- `envs/kronos` (torch 2.15, Kronos-small จาก HF), Kronos clone ที่ `vendor/Kronos` (commit 67b630e)
- `desks/research/kronos_filter.py`: 100 paths ผ่าน `predict_batch` (เพราะ `predict()` เฉลี่ย sample ทิ้ง) → p_up, exp_ret, q10/q50/q90
- `scripts/fetch_candles.py` แคช parquet ที่ `data/candles/` ให้ venv อื่นใช้; `config/universe.yaml` = หุ้นใหญ่ 30 ตัว + BTC/ETH (ใช้วิจัย ไม่ใช่ watchlist เทรด)
- ความเร็ว (Mac M-series): lookback 400 → CPU 36s / MPS 22s ต่อ forecast; lookback 256 → MPS 11s / CPU 20s; RAM ~1.7GB → ใช้ lookback 256
- VPS (2 vCPU, CPU-only torch): ~66s/forecast ที่ lookback 256 (ต้องตั้ง 2 threads; default 1 thread = 121s) → backtest ทั้งชุด ~43 ชม. จึงรันบน Mac แทน; ใช้งานจริงวันละครั้งกับ watchlist 3 ตัว ~3–4 นาที, universe 30 ตัว ~35 นาที (VPS มี Kronos + `envs/kronos` + candles พร้อมแล้ว)
- `backtests/kronos_filter_backtest.py run|report`: out-of-sample เริ่ม 2025-09-01 (หลัง paper Kronos 2025-08 — ไม่รู้ cutoff ของ pre-train แน่ชัด), หุ้น 1d h=5 step 5, crypto 1d h=5 step 5 + 4h h=6 step 12, ประมาณ 2,360 forecasts ~7 ชม. → ผลที่ `backtests/kronos_20261029/`
- สังเกตจาก smoke test (10 paths): BTC 1d ได้ p_up ≤ 0.30 ทุกจุด → อาจมี bias ขาลงจากการ normalize ต้องดู calibration ในผลจริงก่อนใช้เกณฑ์ 0.70

**2026-10-29 — Deploy VPS ใหม่ + cron Phase 1 เริ่มรัน**
- VPS ใหม่ (Vultr) Ubuntu 26.04, 2 vCPU AVX2, RAM 3.3G + swap 4.8G, disk ว่าง 36G, มีทั้ง IPv4 (ใช้กับ OKX whitelist) และ IPv6 — address ดูใน `~/.ssh/config` บน Mac (ไม่เก็บใน repo)
- SSH จาก Mac: `ssh aifund` (root) / `ssh aifund-app` (user aifund ที่รันบอท) ใช้ key `~/.ssh/id_ed25519_aifund` แยกจาก PRS bot (ลบ key prs-bot ออกจาก VPS แล้ว)
- Hardening: ปิด password login, root key-only, ufw เปิดแค่ 22
- โค้ดที่ `/home/aifund/ai-fund` (clone ผ่าน read-only deploy key), `.venv` + `envs/data` ด้วย uv Python 3.12 — test offline + live ผ่านบน VPS
- `.env` ส่งด้วย scp (600) — Telegram ส่งจาก VPS ได้
- cron (UTC): `0 23 * * 1-5 scripts/cron_daily_prices.sh` = 06:00 TH จ–ศ, log ที่ `logs/`, ล้มแล้วแจ้ง Telegram
- เริ่มนับเกณฑ์ผ่าน Phase 1 (5 วันทำการติด) ตั้งแต่เช้า 30 ต.ค. (TH)
- **ค้าง:** Telegram tokens + Alpaca paper key ยังเป็นชุดที่เคยส่งในแชท → **ต้อง revoke/regenerate ก่อน Phase 4**; ANTHROPIC_API_KEY ก่อน Phase 3; OKX sub-account; fork daily_stock_analysis; ตรวจ fx.usdthb; heartbeat
- Deploy: แก้บน Mac → `git push` → `ssh aifund-app 'cd ai-fund && git pull'`

**2026-10-28 — Phase 1 (ส่วนโค้ด) เสร็จ**
- `envs/data` (Python 3.12, uv): openbb-core + openbb-equity + openbb-yfinance, ccxt 4.5, pandas 3.1, pandas_market_calendars
- `core/data.py`: `get_stock_daily` (OpenBB/yfinance), `get_crypto_ohlcv` (ccxt OKX public, แบ่งหน้าเกิน 300 แท่ง), `validate_candles`, `expected_index` (ปฏิทิน NYSE)
  - index = UTC tz-aware, ตัดแท่งที่ยังไม่ปิดทิ้งเสมอ (กัน look-ahead)
- tests: offline 15 ผ่าน, live (`pytest -m live`) 9 ผ่าน — หุ้น 250 วัน + crypto 1h/4h/1d ไม่มีแท่งหาย/ซ้ำ
- `scripts/daily_prices.py [--dry]` สรุปราคาปิด watchlist → Telegram (dry-run ผ่าน, ยังไม่ส่งจริงเพราะยังไม่มี `.env`)
- ค้าง: cron บน VPS ทุกวันทำการ (~06:00 TH), heartbeat, fork daily_stock_analysis → เกณฑ์ผ่าน = มาครบ 5 วันทำการติด

**2026-10-28 — Phase 0 (ส่วนโค้ดบน Mac) เสร็จ**
- git init (ยังไม่มี commit / ยังไม่มี remote), โครงสร้างโฟลเดอร์ + `.gitignore`
- `.env.example` (เพิ่ม `TG_FT_TOKEN` สำหรับ bot freqtrade แยก, `LEDGER_PATH`, `HALT_FLAG_PATH`)
- `config/risk.yaml` (ตรงกับ RISK_RULES หลังแก้ทางเลือก A), `config/watchlist.yaml`
- `core/` เป็น package (`pyproject.toml`, พึ่งแค่ pyyaml): `config.py`, `notify.py` (send-only, stdlib), `ledger.py` (SQLite WAL, 4 ตาราง, orders บังคับมี stop)
- `tests/` 11 tests ผ่าน (`.venv` Python 3.12 ด้วย uv: `uv pip install -e '.[dev]'`)
- `scripts/check_vps.sh` สำหรับตรวจสเปก VPS

**ค้าง (ต้องทำมือ / ต้องการข้อมูล)**
- ยังไม่ได้ตรวจสเปก VPS — ต้องการ SSH หรือให้ผู้ใช้รัน `scripts/check_vps.sh` แล้วส่งผล
- ยังไม่ได้ทดสอบส่ง Telegram จริง (ต้องมี `.env`)
- private GitHub repo + deploy ไป VPS
- งานมือ Phase 0: OKX sub-account, Alpaca paper ($3,000), Telegram bot 2 ตัว, Anthropic spend limit, fork daily_stock_analysis
- `fx.usdthb` ใน risk.yaml เป็นค่าประมาณ 33.0 ต้องตรวจ
