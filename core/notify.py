"""Send-only Telegram notifier. Never logs or prints the token.

Usage: python -m core.notify "message"
"""
from __future__ import annotations

import json
import logging
import sys
import urllib.error
import urllib.request

from core.config import env

log = logging.getLogger(__name__)
MAX_LEN = 4000  # Telegram limit is 4096


def _chunks(text: str, size: int = MAX_LEN) -> list[str]:
    out, buf = [], ""
    for line in text.splitlines(keepends=True):
        while len(line) > size:
            if buf:
                out.append(buf)
                buf = ""
            out.append(line[:size])
            line = line[size:]
        if len(buf) + len(line) > size:
            out.append(buf)
            buf = ""
        buf += line
    if buf:
        out.append(buf)
    return out or [""]


def send(text: str, *, silent: bool = False) -> bool:
    """Return True if every chunk was delivered. Failures are logged, never raised."""
    token, chat_id = env("TG_TOKEN"), env("TG_CHAT_ID")
    if not token or not chat_id:
        log.warning("notify: TG_TOKEN/TG_CHAT_ID not set, message dropped")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    ok = True
    for chunk in _chunks(text):
        body = json.dumps({
            "chat_id": chat_id,
            "text": chunk,
            "disable_notification": silent,
            "disable_web_page_preview": True,
        }).encode()
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                ok &= json.load(resp).get("ok", False)
        except urllib.error.HTTPError as e:
            # e.url contains the token — log only the status
            log.error("notify: Telegram HTTP %s", e.code)
            ok = False
        except (urllib.error.URLError, TimeoutError) as e:
            log.error("notify: network error %s", type(e).__name__)
            ok = False
    return ok


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    msg = " ".join(sys.argv[1:]) or "ai-fund: test message"
    sys.exit(0 if send(msg) else 1)
