# AI Fund — คำแนะนำสำหรับ Claude

ตอบผู้ใช้เป็นภาษาไทย

## อ่านก่อนเริ่มทุก session
1. `CONTEXT.md` — เป้าหมาย, สถาปัตยกรรม 4 desk, แผน phase, log การตัดสินใจ, **สถานะล่าสุด** (บนสุดคือใหม่สุด)
2. `WORKFLOW.md` — checklist ของแต่ละ phase และเกณฑ์ผ่าน
3. `RISK_RULES.md` — กฎความเสี่ยง (ตัวเลขที่โค้ดใช้จริงอยู่ใน `config/risk.yaml`)

ผล backtest และข้อสรุปแต่ละ phase อยู่ใน `backtests/<ชื่อ>_<วันที่>/` (report.md, conclusion.md)

## ข้อห้าม
- LLM เสนอได้แต่ไม่ส่งออเดอร์เอง ทุกออเดอร์ต้องผ่าน `core/risk_gate.py` (deterministic)
- ห้ามส่งออเดอร์ใดๆ (paper หรือ live) จนกว่าจะถึง Phase 4
- ห้ามพิมพ์ค่า API key ลง log/terminal/แชท และห้าม commit `.env` — ผู้ใช้แก้ `.env` เอง
- ห้ามแตะโฟลเดอร์ key, sub-account หรือ Telegram bot ของ PRS bot

## การทำงาน
- พัฒนาบน Mac → `git push` (private repo `ruckids25/ai-fund`, branch main) → `ssh aifund-app 'cd ai-fund && git pull'` บน VPS
- แต่ละ component มี venv แยก: `.venv` (core + pytest), `envs/data`, `envs/kronos`, `envs/ta`
- ก่อนจบ session ให้อัปเดต "สถานะล่าสุด" ใน `CONTEXT.md`
- ถ้า session นี้ใช้เพื่อปรึกษาภาพรวม: อ่านไฟล์ได้ แต่อย่าแก้ไฟล์หรือรันงานยาว เว้นแต่ผู้ใช้สั่ง (อาจมี backtest รันอยู่ใน session อื่น)
