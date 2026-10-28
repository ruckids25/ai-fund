# Risk Rules — AI Fund

> เขียนก่อนเทรดครั้งแรก เปลี่ยนได้เฉพาะตอนไม่มี position เปิดอยู่ และต้องบันทึกเหตุผลใน CONTEXT.md ทุกครั้ง
> ตัวเลขทั้งหมดต้องตรงกับ `config/risk.yaml` ซึ่งเป็นไฟล์เดียวที่โค้ดอ่าน

## 1. งบขาดทุน (Loss Budget)
| กฎ | ค่า | เมื่อถึงแล้ว |
|---|---|---|
| งบขาดทุนรวม | **15,000 THB** | Hard stop: ปิดทุก position, หยุดทุกบอท, ทบทวนด้วยมือก่อนเปิดใหม่ |
| Soft stop | **-7,500 THB** | หยุดเปิด position ใหม่, ทบทวนระบบ 1 สัปดาห์ |
| ขาดทุนต่อวัน | **-600 THB** | ไม่เปิดเทรดใหม่จนถึงวันถัดไป |
| ความเสี่ยงต่อเทรด | **300 THB** (2% ของงบ) | ใช้คำนวณ position size จากระยะ stop |

นับรวม realized + unrealized PnL ข้ามทุก desk (หุ้น + crypto)
ด้วยกฎ 300 THB ต่อเทรด ระบบต้องแพ้ติดกันประมาณ 50 ครั้งจึงจะหมดงบ ทำให้มีเวลาเรียนรู้ก่อนเงินหมด

## 2. Position & Leverage
- **Leverage สูงสุด 5x** ใช้กับ crypto perps เท่านั้น และต้องเป็น **isolated margin**
- หุ้น: ไม่ใช้ margin (cash only)
- ราคา liquidation ต้องอยู่ไกลกว่า stop-loss อย่างน้อย 50% ของระยะ stop ถ้าไม่ผ่าน risk_gate ต้องลด leverage หรือไม่เข้า
- เปิด position พร้อมกันไม่เกิน **3 ตัว** (รวมทุก desk)
- **ทุนแยกตาม desk** (งบขาดทุนในข้อ 1 ยังใช้ร่วมกัน):
  - Crypto (OKX sub-account): **15,000 THB** — ฝากไม่เกินนี้
  - หุ้น (Alpaca paper): **$3,000** — ต้องเท่ากับทุนจริงที่พร้อมใส่ถ้าผ่าน go-live
- Crypto: position เดียวใช้ margin ไม่เกิน **20%** ของบัญชี OKX
- หุ้น: มูลค่า position เดียวไม่เกิน **33%** ของทุนหุ้น และรวมทุกตัวไม่เกินทุนหุ้น (cash only)

## 3. Stop-loss
- ทุกออเดอร์ต้องมี stop-loss **วางไว้ที่ exchange/broker** (bracket order / stop order) ไม่ใช่แค่เช็คในโค้ด
- ห้ามขยับ stop ให้ห่างออก ขยับได้แค่ทางที่ลดความเสี่ยง

## 4. ค่า API (นับแยกจากงบขาดทุน)
- ตั้ง **monthly spend limit** ที่ Anthropic console (เริ่มต้น $30/เดือน แก้ได้)
- TradingAgents รันเฉพาะตัวที่ผ่าน Kronos filter และไม่เกิน **5 ticker ต่อวัน**
- บันทึกค่า API ต่อรอบลง ledger ถ้าค่า API ต่อเดือนสูงกว่ากำไรเฉลี่ยใน paper ต้องทบทวน

## 5. Kill Switches (ทดสอบทุกเดือน)
- Telegram: freqtrade `/stopentry`, `/forceexit all`
- `fund.py --halt`: ตั้ง flag ที่ทำให้ทุก run ถัดไปไม่ส่งออเดอร์
- risk_gate หยุดเองอัตโนมัติเมื่อถึง soft/hard stop
- ปิด API key ที่ exchange ด้วยมือ (ทางสุดท้าย)

## 6. ความปลอดภัยของ Key
- OKX: sub-account ใหม่สำหรับระบบนี้เท่านั้น สิทธิ์ **Trade อย่างเดียว ปิด Withdraw** ผูก IP whitelist กับ VPS
- **ไม่แชร์ key, sub-account หรือ Telegram bot กับ PRS bot**
- `.env` ห้าม commit, ห้ามพิมพ์ key ลง log
- เครื่องที่รัน RD-Agent ต้องไม่มี credential จริงอยู่เลย

## 7. เกณฑ์ Go-Live (ต้องผ่านครบทุกข้อ)
- [ ] Walk-forward backtest รวม fee + funding/slippage แล้วยังมีกำไร
- [ ] ผ่าน look-ahead check (freqtrade `lookahead-analysis` / ตรวจ timestamp ใน fund.py)
- [ ] Paper/dry-run ต่อเนื่อง ≥ 30 วัน
- [ ] Max drawdown ใน paper ไม่เกิน soft stop เมื่อแปลงเป็นขนาดจริง
- [ ] ทดสอบ kill switch ครบทุกตัวแล้ว
- [ ] มีเทรดใน paper อย่างน้อย **30 เทรด** ต่อ desk (30 วันอย่างเดียวไม่พอสรุปผล)
- [ ] (หุ้น) มีบัญชีเงินจริงที่เปิดได้ และใส่ทุนได้เท่ากับทุนหุ้นที่ใช้ใน paper — ถ้ายังไม่มี desk หุ้นอยู่ใน paper ต่อ
- [ ] เริ่ม live ด้วย **ไม่เกิน 25%** ของขนาดที่วางแผน
