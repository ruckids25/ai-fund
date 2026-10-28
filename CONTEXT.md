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
- [ ] สเปก VPS (RAM/CPU) พอสำหรับ Kronos-small บน CPU หรือไม่
- [ ] TradingAgents รองรับ crypto ได้ดีแค่ไหน ถ้าไม่ดี committee ฝั่ง crypto ใช้ strategy rule-based แทน
- [ ] อัตราแลกเปลี่ยน THB/USD สำหรับแปลงงบใน `risk.yaml`

## Log การตัดสินใจ
- 2026-10-27: เลือกตาม stack ในบทความ "10 GitHub repos" ครอบคลุมหุ้น + crypto, เริ่มใหม่ไม่ใช้ strategy เดิม, แยกจาก PRS bot, งบขาดทุน 15K THB, leverage ≤ 5x, ตัด hummingbot และ funding arb
- 2026-10-28: พัฒนาบน Mac → private GitHub repo → `git pull` บน VPS (แทนการเขียนบน VPS ตรงๆ), สเปก VPS ให้ตรวจตอน Phase 0, ทุนบัญชีบอท = 15,000 THB (เท่างบขาดทุน — OKX ฝากไม่เกินนี้, Alpaca paper ตั้ง equity เทียบเท่า), strategy crypto ตัวแรก: Claude เสนอ 2–3 แบบให้เลือกก่อน Phase 4, THB/USD: fix ใน risk.yaml อัปเดตรายสัปดาห์ (default จนกว่าจะเปลี่ยน)
- 2026-10-28: แก้ RISK_RULES ข้อ 2 และ 7 (ยังไม่มี position เปิด) — เหตุผล: ทุน 15K THB + กฎ margin 20% ทำให้หุ้นแบบเงินสดเสี่ยงได้แค่ ~120 THB/เทรด และเปิด 3 ตัวไม่ได้ จึงแยกทุนหุ้นใน paper = $3,000 (ค่าเริ่มต้น ต้องเท่าทุนจริงที่พร้อมใส่), cap หุ้น 33%/ตัว, งบขาดทุน 15K ยังใช้ร่วมกัน, เพิ่มเกณฑ์ ≥30 เทรด/desk และต้องมีบัญชีหุ้นจริงก่อน go-live ฝั่งหุ้น

## สถานะล่าสุด
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
