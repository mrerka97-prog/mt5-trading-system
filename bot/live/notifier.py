"""Telegram мэдэгдэл ба команд (/status, /pause, /resume, /stop). Token байхгүй бол зөвхөн лог."""
from __future__ import annotations

import json
import logging
import time
import urllib.parse
import urllib.request

log = logging.getLogger("bot")


class Notifier:
    def __init__(self, token: str | None, chat_id: str | None):
        self.token, self.chat_id = token, str(chat_id) if chat_id else None
        self.enabled = bool(token and chat_id)

    def _call(self, method: str, params: dict) -> dict | None:
        url = f"https://api.telegram.org/bot{self.token}/{method}"
        data = urllib.parse.urlencode(params).encode()
        try:
            with urllib.request.urlopen(url, data=data, timeout=10) as r:
                return json.loads(r.read().decode())
        except Exception as e:  # сүлжээний алдаа ботыг зогсоох ёсгүй
            log.warning("Telegram алдаа: %s", e)
            return None

    def send(self, text: str) -> None:
        log.info("[TG] %s", text.replace("\n", " | "))
        if self.enabled:
            self._call("sendMessage", {"chat_id": self.chat_id, "text": text})

    def poll_messages(self, offset: int, timeout: int = 25) -> tuple[list[str], int]:
        """Зөвхөн тохируулсан chat_id-аас ирсэн мессежүүдийг (бүтэн текстээр) буцаана. Long polling."""
        if not self.enabled:
            return [], offset
        url = f"https://api.telegram.org/bot{self.token}/getUpdates"
        data = urllib.parse.urlencode({"offset": offset, "timeout": timeout}).encode()
        try:
            with urllib.request.urlopen(url, data=data, timeout=timeout + 10) as r:
                res = json.loads(r.read().decode())
        except Exception as e:
            log.warning("Telegram getUpdates алдаа: %s", e)
            time.sleep(10)                         # интернэт тасарсан үед лог дүүргэхгүй
            return [], offset
        msgs = []
        for u in res.get("result", []):
            offset = max(offset, u["update_id"] + 1)
            msg = u.get("message") or {}
            if str(msg.get("chat", {}).get("id")) == self.chat_id and msg.get("text"):
                msgs.append(msg["text"].strip())
        return msgs, offset

    def poll_commands(self, offset: int) -> tuple[list[str], int]:
        """Зөвхөн тохируулсан chat_id-аас ирсэн командуудыг буцаана."""
        if not self.enabled:
            return [], offset
        res = self._call("getUpdates", {"offset": offset, "timeout": 0})
        cmds = []
        for u in (res or {}).get("result", []):
            offset = max(offset, u["update_id"] + 1)
            msg = u.get("message") or {}
            if str(msg.get("chat", {}).get("id")) == self.chat_id and msg.get("text", "").startswith("/"):
                cmds.append(msg["text"].split()[0].lower())
        return cmds, offset
