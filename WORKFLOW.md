# AI Fund — Workflow ตั้งแต่ศูนย์จนพร้อม Go-Live

> สร้างจาก CONTEXT.md / RISK_RULES.md / KICKOFF_PROMPT.md (2026-10-28)
> ใช้คู่กับ CONTEXT.md: ไฟล์นี้บอก "ทำอะไร ลำดับไหน ผ่านเมื่อไหร่" ส่วน CONTEXT.md บอก "ทำไม และสถานะล่าสุด"

---

## 0. ภาพรวม: 3 ลูปที่ต้องสร้าง

```
(A) ลูปพัฒนา      : Claude Code session → โค้ด + test → commit → deploy VPS → อัปเดต CONTEXT.md
(B) ลูปเทรดรายวัน  : ข้อมูล → Kronos (กรองถูก) → TradingAgents (กรองแพง) → risk_gate → order → ledger → Telegram
(C) ลูปเฝ้าระวัง   : risk_monitor ทุก 5 นาที (crypto 24/7) → เช็ค soft/hard/daily stop → halt / ปิด position / แจ้งเตือน
```

ลูป (C) **ไม่มีในแผนเดิม** แต่จำเป็น เพราะ RISK_RULES นับ unrealized PnL และ crypto เปิด 24 ชม. ถ้าเช็คแค่ตอน fund.py รันวันละครั้ง hard stop จะมาช้าเกินไป

---

## 1. Workflow ลูปพัฒนา (ทุก session)

1. เปิด session → ให้ Claude อ่าน `CONTEXT.md`, `RISK_RULES.md`, `WORKFLOW.md`
2. ระบุ phase + ข้อย่อยที่จะทำ (ทำทีละ phase ห้ามข้าม)
3. เขียนโค้ด + test (pytest) → รัน test ผ่านก่อน commit
4. commit (ห้ามมี `.env`) → `git pull` บน VPS → restart service
5. ปิด session: อัปเดต "สถานะล่าสุด" + "Log การตัดสินใจ" ใน CONTEXT.md, ติ๊ก checklist ในไฟล์นี้
6. วันศุกร์: เขียน `journal/YYYY-WW.md` (ลองอะไร / ผลอะไร / จะเปลี่ยนอะไร)

---

## 2. Phase-by-Phase (รายละเอียด + เกณฑ์ผ่าน)

### Phase 0 — Setup (สัปดาห์ 1)
**ทำมือ (นอก Claude Code)**
- [ ] OKX: สร้าง sub-account ใหม่, API key สิทธิ์ Trade อย่างเดียว, ปิด Withdraw, IP whitelist = VPS
- [ ] Alpaca: เปิด paper account, ตั้ง starting equity ให้ใกล้ทุนจริงที่จะใช้ (ดูข้อ 5.2)
- [ ] Telegram: สร้าง bot ใหม่ 2 ตัว (ดูข้อ 5.6) + หา chat_id
- [ ] Anthropic console: monthly spend limit $30
- [ ] fork `daily_stock_analysis` + ใส่ secrets (GitHub Actions)

**ทำใน Claude Code**
- [x] git init + โครงสร้างโฟลเดอร์ + `.gitignore`
- [x] `.env.example`, `config/risk.yaml`, `config/watchlist.yaml`
- [x] `core/notify.py` (send-only), `core/ledger.py` (SQLite WAL mode)
- [x] ตรวจสเปก VPS (VPS เดิมไม่พอ → เช่าใหม่ 2 vCPU/3.3G)

**เกณฑ์ผ่าน:** `.env` ครบ, `python -m core.notify "hello"` ส่งได้, ledger สร้างตารางได้, รายงานสเปก VPS

### Phase 1 — Data layer (สัปดาห์ 1–2)
- [x] venv `envs/data` + `core/data.py` (`get_stock_daily`, `get_crypto_ohlcv`)
- [x] test: candle ไม่หาย/ไม่ซ้ำ (ใช้ปฏิทินตลาด NYSE ไม่ใช่นับวันธรรมดา — วันหยุด US จะทำให้ test fail หลอก)
- [x] timestamp ทุกตัวเป็น UTC, tz-aware
- [x] cron ส่งราคาปิดล่าสุดเข้า Telegram ทุกวันทำการ (VPS 23:00 UTC จ–ศ)
- [ ] **เพิ่ม:** heartbeat — ถ้าไม่มีข้อความเข้า Telegram ภายในเวลาที่กำหนด แปลว่าระบบตาย

**เกณฑ์ผ่าน:** morning note + ราคาปิด มาทุกวันทำการ 5 วันติด

### Phase 2 — Kronos filter + validation (สัปดาห์ 2–3)
- [x] venv `envs/kronos` (torch CPU) + clone Kronos ลง `vendor/`
- [x] `desks/research/kronos_filter.py`: input candle → 100 paths → คืน `p_up`, expected return, quantile
- [x] **Backtest ตัว filter:** walk-forward บนข้อมูลที่ Kronos ไม่เคยเห็น (หลัง training cutoff ของโมเดล)
  - วัด: hit rate ของ `p_up ≥ 0.70` เทียบกับ base rate (% วันขึ้นทั้งหมด), จำนวนสัญญาณต่อเดือน, เวลารันต่อ ticker
- [x] บันทึกผลลง `backtests/kronos_YYYYMMDD/` → `backtests/kronos_20261029/` **ไม่ผ่าน** (hit rate ไม่ต่างจาก base, calibration แบน) → Kronos เป็นข้อมูลให้ committee

**เกณฑ์ผ่าน:** hit rate สูงกว่า base rate อย่างมีนัย (ไม่ใช่แค่ > 50%) และรู้ว่าต่อเดือนมีกี่สัญญาณ
**ถ้าไม่ผ่าน:** ใช้ Kronos เป็นแค่ feature/ข้อมูลให้ committee แทนการเป็นด่านกรอง

### Phase 3 — TradingAgents (สัปดาห์ 3–4)
- [x] venv `envs/ta` + `desks/committee/ta_committee.py` → output JSON มาตรฐาน: `{ticker, action, entry, stop, target, confidence, rationale, cost_usd}`
- [x] วัดค่า API ต่อรอบจริง (token ทุก agent) → ลง `api_costs` (Gemini free tier: ~120K token/รอบ, 18 calls, ~3.5 นาที)
- [ ] ทดลองแบ่งโมเดล: analyst ใช้ Haiku, debate/decision ใช้ Sonnet → เทียบคุณภาพ vs ค่าใช้จ่าย
- [x] backtest grid **เฉพาะช่วงหลัง knowledge cutoff ของโมเดล** (ดูข้อ 5.4) → DeepSeek 5 หุ้น × 8 วัน `backtests/ta_20261030_deepseek/`: ~$0.16/cell, **ยังไม่เห็น edge** เทียบ buy-and-hold

**เกณฑ์ผ่าน:** รู้ $/รอบ, รู้ว่างบ $30/เดือน รันได้กี่ ticker/วันจริงๆ, มีผลเทียบกับ buy-and-hold

### Phase 4 — Risk gate + Execution loop (สัปดาห์ 4–5)
- [ ] `core/risk_gate.py` — pure Python (พึ่งแค่ pyyaml) เพื่อ `pip install -e` เข้าได้ทุก venv
  - `size_position(entry, stop, fx)` → จำนวนหุ้น/contract จาก 300 THB
  - `check_limits()` → daily / soft / hard / max 3 positions / margin ≤ 20%
  - `check_liquidation(entry, stop, lev)` → liq ต้องห่างกว่า stop ≥ 50% ของระยะ stop
  - `is_halted()` → อ่าน halt flag
  - **unit test ครบทุกกฎ** (นี่คือไฟล์สำคัญที่สุดในระบบ)
- [ ] `fund.py` (หุ้น) + `fund.py --halt` / `--dry`
- [ ] Alpaca paper bracket order
- [ ] freqtrade dry-run OKX: strategy แรก + เรียก risk_gate ใน callbacks (`custom_stake_amount`, `leverage`, `confirm_trade_entry`), `stoploss_on_exchange: true`, `margin_mode: isolated`
- [ ] `risk_monitor.py` (ลูป C) อ่าน PnL จาก Alpaca + freqtrade API → รวมเป็น THB → ตัดสินใจ halt
- [ ] `lookahead-analysis` + `recursive-analysis` ของ freqtrade
- [ ] รันด้วย systemd timer / docker-compose + restart อัตโนมัติ + backup ledger รายวัน

**เกณฑ์ผ่าน:** รันครบลูปเอง 5 วันทำการติดโดยไม่แตะมือ, kill switch ทดสอบผ่านทุกตัว

### Phase 5 — Paper 30 วัน (สัปดาห์ 5–8)
- [ ] ไม่แก้ strategy ระหว่าง 30 วัน (แก้ = เริ่มนับใหม่) แก้ได้แค่ bug
- [ ] journal รายสัปดาห์ + รายงานอัตโนมัติวันอาทิตย์: PnL, win rate, avg R, max DD, API cost
- [ ] ตรวจ checklist Go-Live ใน RISK_RULES ข้อ 7

### Phase 6 — หลัง Go-Live
- live ที่ ≤ 25% ของขนาด → ขยายทีละขั้นหลังผ่านแต่ละ 30 วัน
- RD-Agent (เครื่องแยก), NautilusTrader, ai-hedge-fund เทียบผล — ทีละตัว

---

## 3. Workflow รายวัน (Runtime)

เวลาไทย (ระวัง: US DST จบ **1 พ.ย. 2026** → ตลาดเปิด 21:30 และปิด 04:00 เวลาไทย ให้ใช้ปฏิทิน NYSE แทน hard-code เวลา)

| เวลา (TH) | งาน | Process |
|---|---|---|
| ทุก 5 นาที | risk_monitor: รวม PnL, เช็ค stop ทั้งหมด | systemd timer |
| 24/7 | freqtrade dry-run crypto (เรียก risk_gate ทุก entry) | docker |
| ~06:00 | morning note (daily_stock_analysis) | GitHub Actions |
| ~06:00 | fund.py: ดึง candle ปิดเมื่อคืน → Kronos → TradingAgents (≤5) → risk_gate → วาง bracket order ให้ทำงานตอนตลาดเปิดคืนนี้ | cron |
| ~06:30 | สรุป Telegram: สัญญาณ, ออเดอร์, ค่า API, PnL สะสม vs งบ | fund.py |
| 23:59 UTC | snapshot daily_pnl ลง ledger + backup | cron |
| อาทิตย์ | รายงานสัปดาห์ + ทดสอบ kill switch (เดือนละครั้ง) | cron + มือ |

---

## 4. การตัดสินใจ (ตอบแล้ว 2026-10-28)

1. **พัฒนาที่ไหน:** ✅ Mac → private GitHub repo → `git pull` บน VPS
2. **สเปก VPS:** ⏳ Claude ตรวจเองตอน Phase 0 (ต้องมีสิทธิ์ SSH เข้า VPS)
3. **ทุนบัญชีบอท:** ✅ 15,000 THB (= งบขาดทุน) → margin ต่อ position ≤ 3,000 THB
4. **Strategy crypto ตัวแรก:** ⏳ Claude เสนอ 2–3 แบบให้เลือกก่อน Phase 4
5. **THB/USD:** ✅ (default) fix ใน risk.yaml อัปเดตรายสัปดาห์

6. **ทุนหุ้น:** ✅ ทางเลือก A — แยกทุนหุ้นใน paper $3,000 (ค่าเริ่มต้น), งบขาดทุนใช้ร่วม, แก้ RISK_RULES ข้อ 2/7 แล้ว

### (ปิดแล้ว) ผลกระทบจากข้อ 3
ทุน 15K THB ≈ $420 → กฎ 20% ต่อ position = **~$85 ต่อตัว**
- **Crypto:** ใช้ได้ (5x → notional ~$420, OKX ขั้นต่ำ BTC/ETH perp เล็กพอ)
- **หุ้น:** NVDA/AAPL/MSFT ราคา $150–500 ต่อหุ้น ซื้อไม่ได้แม้แต่ 1 หุ้นภายใต้ $85 และ bracket order ใช้ fractional ไม่ได้
- ทางเลือก: (ก) กฎ 20% ใช้กับ crypto เท่านั้น หุ้นใช้ cap แยก (ข) หุ้นใช้ fractional + stop order แยก (ต้องตรวจว่า Alpaca รองรับ) (ค) ใช้ ETF/หุ้นราคาต่ำ (ง) ตั้ง paper equity หุ้นตามทุนจริงในอนาคต แยกจากงบ crypto

---

## 5. ข้อสังเกต / Idea ที่ดีกว่า

### 5.1 Watchlist 3 ตัวเล็กเกินไปที่จะวัดผล
NVDA/AAPL/MSFT + Kronos 70% อาจได้สัญญาณแค่ไม่กี่ครั้งต่อเดือน → 30 วัน paper อาจมี < 10 เทรด ซึ่ง **สรุปทางสถิติไม่ได้เลย**
**แนะนำ:** ใช้ universe ใหญ่ (เช่น 30–50 หุ้น liquid ใน S&P100) สำหรับ Kronos filter (ถูก) แล้วค่อยส่งให้ TradingAgents ≤5 ตัว และเพิ่มเกณฑ์ Go-Live: **ต้องมี ≥ 30 เทรด** ไม่ใช่แค่ ≥ 30 วัน

### 5.2 300 THB/เทรด ≈ $9 — เล็กมากสำหรับหุ้นราคาสูง
- MSFT ~$500, stop 2% = $10/หุ้น → ซื้อได้ 0 หุ้น
- Alpaca **bracket order ไม่รองรับ fractional shares** → หลายเทรดจะถูก risk_gate ปัดเป็น 0
- ทางเลือก: (ก) เพิ่ม risk/เทรดฝั่งหุ้นใน paper ให้สมจริงตามทุนจริงที่จะใช้ (ข) ใช้ universe ราคาต่อหุ้นต่ำกว่า (ค) ใช้ stop order แยกแทน bracket (fractional ใช้ได้บางประเภท — ต้องตรวจ)
- **ตัดสินใจก่อน Phase 4** ไม่งั้น paper ไม่สะท้อน live

### 5.3 ฝากเงินเข้า OKX sub-account ไม่เกินงบขาดทุน
วิธีที่ปลอดภัยที่สุดคือให้ "exchange เป็น hard stop เอง": ฝากเท่าที่ยอมเสียได้ (เช่น ≤ 15K THB) → ต่อให้โค้ดพังทั้งหมด ก็เสียไม่เกินนี้ (ฝั่งหุ้นเป็น cash-only ไม่มีความเสี่ยงติดลบอยู่แล้ว)

### 5.4 Backtest ที่ใช้ LLM มี look-ahead bias แฝง
Claude รู้อยู่แล้วว่า NVDA ปี 2024 ขึ้นแรง → backtest TradingAgents ย้อนช่วงก่อน knowledge cutoff จะดีเกินจริง
**แนะนำ:** เชื่อเฉพาะผลช่วงหลัง cutoff + paper forward เท่านั้น (Kronos ก็เช่นกัน: ตรวจช่วง training data ของโมเดลก่อน)

### 5.5 ค่า API อาจไม่พอ
TradingAgents หนึ่งรอบเรียก LLM หลายสิบครั้ง (analysts + bull/bear debate + risk debate) ถ้า ~$0.5–1/รอบ × 5 ticker × 21 วัน = $50–100/เดือน > $30
→ Phase 3 ต้องวัดจริง แล้วปรับ: ลดรอบ debate, ใช้ Haiku กับ analyst, หรือลดเหลือ 2–3 ticker/วัน

### 5.6 Telegram: แยก bot "สั่งงาน" กับ "แจ้งเตือน"
freqtrade ใช้ polling (`getUpdates`) — ถ้า process อื่นใช้ token เดียวกันมา poll ด้วยจะชนกัน
→ bot ที่ 1 = freqtrade (มีคำสั่ง `/stopentry`, `/forceexit`), bot ที่ 2 = notify.py (send-only) + คำสั่ง `/halt` ของ fund.py

### 5.7 risk_gate ต้องใช้ได้ข้าม venv
freqtrade, TradingAgents, Kronos อยู่คนละ venv แต่ทุกตัวต้องเรียก risk_gate → ทำ `core/` เป็น package เล็ก dependency น้อย (`pyyaml` เท่านั้น) แล้ว `pip install -e .` เข้าทุก venv; ledger ใช้ SQLite WAL mode รองรับหลาย process เขียนพร้อมกัน

### 5.8 พิจารณาข้าม OpenBB
OpenBB ติดตั้งหนักและเปลี่ยน API บ่อย ถ้าใช้แค่ candle รายวัน `yfinance` ตรงๆ หรือ `alpaca-py` (data API ฟรี) เบากว่ามาก — ซ่อนไว้หลัง `core/data.py` อยู่แล้ว เปลี่ยนทีหลังได้

### 5.9 เพิ่ม Benchmark
ทุกรายงานควรเทียบกับ buy-and-hold SPY / BTC ในช่วงเดียวกัน ถ้าบอทแพ้ buy-and-hold ก็ยังไม่ควร go-live แม้จะกำไร

### 5.10 Housekeeping
- เปลี่ยนชื่อไฟล์ `*_1.md` → `CONTEXT.md`, `RISK_RULES.md`, `KICKOFF_PROMPT.md` ให้ตรงกับที่เอกสารอ้างถึง
- เพิ่ม `.env` permission `chmod 600`, NTP sync บน VPS, log rotation
