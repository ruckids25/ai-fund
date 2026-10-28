# Prompt สำหรับวางใน Claude Code บน VPS (Phase 0–1)

วาง CONTEXT.md และ RISK_RULES.md ไว้ในโฟลเดอร์ `ai-fund/` ก่อน แล้วเปิด Claude Code ในโฟลเดอร์นั้นและวางข้อความด้านล่าง

---

อ่าน CONTEXT.md และ RISK_RULES.md ให้ครบก่อน แล้วทำเฉพาะ Phase 0 และ Phase 1 ห้ามข้ามไป phase อื่น

**Phase 0 — Setup**
1. git init และสร้างโครงสร้างโฟลเดอร์ตาม CONTEXT.md พร้อม `.gitignore` (รวม `.env`, `vendor/`, `user_data/data/`, `logs/`)
2. สร้าง `.env.example` ที่มีตัวแปร: ANTHROPIC_API_KEY, ALPACA_API_KEY, ALPACA_SECRET_KEY, OKX_API_KEY, OKX_SECRET, OKX_PASSPHRASE, TG_TOKEN, TG_CHAT_ID, TAVILY_API_KEYS
3. สร้าง `config/risk.yaml` จากตัวเลขใน RISK_RULES.md และ `config/watchlist.yaml` (หุ้น: NVDA, AAPL, MSFT / crypto: BTC/USDT:USDT, ETH/USDT:USDT)
4. เขียน `core/notify.py` (ส่ง Telegram) และ `core/ledger.py` (SQLite: ตาราง decisions, orders, api_costs, daily_pnl)
5. ตรวจสเปก VPS (RAM, CPU, disk, มี GPU ไหม) แล้วรายงานว่าพอสำหรับ Kronos-small บน CPU หรือไม่

**Phase 1 — Data layer**
6. สร้าง venv แยกสำหรับ data layer ติดตั้ง openbb, openbb-equity, openbb-yfinance, ccxt, pandas
7. เขียน `core/data.py` ที่มี:
   - `get_stock_daily(ticker, days)` ผ่าน OpenBB (yfinance)
   - `get_crypto_ohlcv(symbol, timeframe, limit)` ผ่าน ccxt บน OKX (public data, ยังไม่ต้องใช้ key)
   - คืนค่าเป็น DataFrame คอลัมน์ open, high, low, close, volume พร้อม timestamp
8. เขียน test สั้นๆ ที่ดึงข้อมูลทุกตัวใน watchlist แล้วตรวจว่าไม่มี candle หาย/ซ้ำ
9. ส่งข้อความ Telegram ทดสอบ: ราคาปิดล่าสุดของทุกตัวใน watchlist

**ข้อห้าม**
- ห้ามส่งออเดอร์ใดๆ ทั้ง paper และ live ใน phase นี้
- ห้ามพิมพ์ค่า API key ลง log หรือ terminal
- ห้ามแตะโฟลเดอร์หรือ key ของ PRS bot

เมื่อเสร็จ ให้อัปเดตส่วน "สถานะล่าสุด" ใน CONTEXT.md และสรุปว่าอะไรเสร็จ อะไรติด และสเปก VPS พอหรือไม่

---

**นอก Claude Code (ทำมือ):** fork `ZhuLinsen/daily_stock_analysis` แล้วใส่ secrets ตามบทความ เพื่อให้ morning note เริ่มมาตั้งแต่สัปดาห์แรก (รันบน GitHub Actions ไม่ใช้ VPS)
