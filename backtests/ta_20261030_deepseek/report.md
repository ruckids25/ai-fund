# TradingAgents committee grid — backtests/ta_20261030_deepseek

cells: 40 | tickers: NVDA, AAPL, MSFT, JPM, XOM | dates: 2026-08-31 → 2026-10-19 | horizon 5 sessions

buy-and-hold (ทุก cell): mean +0.55%, ขึ้น 55%

| action | n | mean ret5 | ขึ้น | edge vs ทุก cell |
|---|---|---|---|---|
| buy | 15 | +0.14% | 53% | -0.41% |
| hold | 5 | +0.43% | 40% | -0.13% |
| sell | 20 | +0.89% | 60% | +0.34% |

| rating | n | mean ret5 |
|---|---|---|
| Hold | 5 | +0.43% |
| Overweight | 15 | +0.14% |
| Underweight | 20 | +0.89% |

buy signals: 15 | มี stop 93% | ระยะ stop เฉลี่ย 3.7% | 10 sessions: open 8, stop 5, target 2

long-only ตาม buy (cell อื่นถือเงินสด): mean ต่อ cell +0.05% vs ถือทุก cell +0.55%

เวลาเฉลี่ย 552s/cell | token เฉลี่ย in 189,607 / out 80,023 | calls 21