"""Telegram alert channel — the owner-paging path for unattended sessions.

Free at any volume (Telegram Bot API has no charges). Stdlib-only. A send
failure must never take the session down: errors are logged and swallowed —
the session's own log remains the fallback channel.

Setup (one time):  python -m optionsbot.paper --telegram-setup
Secret layout:     tradingbot/telegram = {"TELEGRAM_BOT_TOKEN": ..., "TELEGRAM_CHAT_ID": ...}
"""
from __future__ import annotations

import json
from typing import Callable
from urllib import parse, request


def _http_post(url: str, data: bytes | None = None, timeout: float = 10.0) -> bytes:
    with request.urlopen(url, data=data, timeout=timeout) as resp:
        return resp.read()


class TelegramAlerter:
    def __init__(
        self,
        token: str,
        chat_id: str,
        log: Callable[[str], None] = lambda msg: None,
        http: Callable[..., bytes] = _http_post,
    ) -> None:
        self._token = token
        self._chat_id = chat_id
        self._log = log
        self._http = http

    def send(self, message: str) -> bool:
        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        data = parse.urlencode(
            {"chat_id": self._chat_id, "text": f"optionsbot: {message}"}
        ).encode()
        try:
            self._http(url, data)
            return True
        except Exception as exc:  # alerting must never crash the session
            self._log(f"telegram send failed: {exc!r} — message was: {message}")
            return False


def discover_chat_id(token: str, http: Callable[..., bytes] = _http_post) -> str | None:
    """Chat ID of the most recent message sent to the bot (the owner must have
    messaged the bot at least once)."""
    raw = http(f"https://api.telegram.org/bot{token}/getUpdates")
    updates = json.loads(raw)
    for update in reversed(updates.get("result", [])):
        message = update.get("message") or update.get("edited_message") or {}
        chat = message.get("chat") or {}
        if chat.get("id") is not None:
            return str(chat["id"])
    return None
