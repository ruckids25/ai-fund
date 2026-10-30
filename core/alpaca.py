"""Minimal Alpaca PAPER client (stdlib only). The URL is fixed: this cannot reach live.

Never logs or prints the keys. Entry orders are GTC because the stop leg of a DAY
bracket expires at the close, which would leave a position without a broker stop
(RISK_RULES 3); fund.py cancels entries that stayed unfilled on its next run.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from core.config import env

PAPER_URL = "https://paper-api.alpaca.markets"


class AlpacaError(RuntimeError):
    pass


def order_payload(symbol: str, qty: float, entry: float, stop: float, target: float | None,
                  client_id: str) -> dict:
    """Limit entry with a broker-side stop, plus take-profit when the target is usable."""
    body = {
        "symbol": symbol, "qty": str(int(qty)), "side": "buy", "type": "limit",
        "time_in_force": "gtc", "limit_price": f"{entry:.2f}", "client_order_id": client_id,
        "order_class": "oto", "stop_loss": {"stop_price": f"{stop:.2f}"},
    }
    if target and target > entry:
        body["order_class"] = "bracket"
        body["take_profit"] = {"limit_price": f"{target:.2f}"}
    return body


class AlpacaPaper:
    def __init__(self):
        flag = (env("ALPACA_PAPER", "true") or "").lower()
        if flag != "true" and not flag.startswith(PAPER_URL):   # .env may hold the paper URL
            raise AlpacaError("ALPACA_PAPER is not paper; this client is paper only")
        self._headers = {"APCA-API-KEY-ID": env("ALPACA_API_KEY") or "",
                         "APCA-API-SECRET-KEY": env("ALPACA_SECRET_KEY") or "",
                         "Content-Type": "application/json"}

    def _call(self, method: str, path: str, body: dict | None = None, **params):
        url = f"{PAPER_URL}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, headers=self._headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            raise AlpacaError(f"{method} {path}: HTTP {e.code} {e.read()[:200].decode(errors='replace')}") from None
        except (urllib.error.URLError, TimeoutError) as e:
            raise AlpacaError(f"{method} {path}: {type(e).__name__}") from None
        return json.loads(raw) if raw else None

    def account(self) -> dict:
        return self._call("GET", "/v2/account")

    def clock(self) -> dict:
        return self._call("GET", "/v2/clock")

    def calendar(self, start: str, end: str) -> list[dict]:
        return self._call("GET", "/v2/calendar", start=start, end=end)

    def positions(self) -> list[dict]:
        return self._call("GET", "/v2/positions")

    def open_orders(self) -> list[dict]:
        return self._call("GET", "/v2/orders", status="open", nested="true", limit=500)

    def submit(self, payload: dict) -> dict:
        return self._call("POST", "/v2/orders", payload)

    def cancel(self, order_id: str) -> None:
        self._call("DELETE", f"/v2/orders/{order_id}")

    def close_all(self) -> None:
        self._call("DELETE", "/v2/positions", cancel_orders="true")
