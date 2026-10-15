"""Telegram-ийг нэг удаа тохируулах: chat ID-г олж .env-д бичээд, туршилтын мессеж илгээнэ.

Өмнө нь:  .env файлд TELEGRAM_BOT_TOKEN=... -г бичсэн, Telegram дээр өөрийн ботод мессеж бичсэн байх.
Ажиллуулах:  python scripts/telegram_setup.py
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from dotenv import load_dotenv  # noqa: E402

from bot.config import ROOT     # noqa: E402

ENV = ROOT / ".env"


def api(token: str, method: str, params: dict | None = None) -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = urllib.parse.urlencode(params or {}).encode()
    with urllib.request.urlopen(url, data=data, timeout=15) as r:
        return json.loads(r.read().decode())


def set_env(key: str, value: str) -> None:
    lines = ENV.read_text(encoding="utf-8").splitlines()
    for i, ln in enumerate(lines):
        if ln.strip().startswith(f"{key}="):
            lines[i] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    load_dotenv(ENV)
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token or ":" not in token:
        print("[XX] .env файлд TELEGRAM_BOT_TOKEN бичигдээгүй байна.")
        print("     @BotFather-оос авсан token-оо TELEGRAM_BOT_TOKEN= гэсний ард бичээд хадгална уу.")
        return 1
    try:
        me = api(token, "getMe")
    except Exception as e:
        print(f"[XX] Token буруу эсвэл интернэт алга: {e}")
        return 1
    print(f"[OK] Бот олдлоо: @{me['result']['username']}")

    upd = api(token, "getUpdates").get("result", [])
    chats = [u["message"]["chat"] for u in upd if "message" in u]
    if not chats:
        print("[XX] Ботод ирсэн мессеж алга.")
        print(f"     Telegram дээр @{me['result']['username']}-ийг нээж Start дарах эсвэл 'hi' гэж бичээд,")
        print("     энэ скриптийг дахин ажиллуулна уу.")
        return 1
    chat = chats[-1]
    chat_id = str(chat["id"])
    set_env("TELEGRAM_CHAT_ID", chat_id)
    print(f"[OK] Chat ID олдлоо ({chat.get('first_name', '')}) ба .env-д бичигдлээ.")

    api(token, "sendMessage", {"chat_id": chat_id, "text":
        "✅ Forex бот Telegram-тэй холбогдлоо!\n\nКомандууд (telegram_listener.py ажиллаж байх үед):\n"
        "/check EURUSD BUY — арилжааны санал шалгах\n/status — данс, позиц\n"
        "/pause, /resume — шинэ арилжааг түр зогсоох/үргэлжлүүлэх\n/stop — бүх позицыг хааж ботыг зогсоох\n/help"})
    print("[OK] Туршилтын мессеж илгээлээ. Утсаа шалгана уу.")
    print("\nДараа нь:  python scripts/telegram_listener.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
