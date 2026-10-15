"""Тохиргоо: config/config.yaml (стратеги, эрсдэл) + .env (нууц мэдээлэл)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Secrets:
    mt5_login: int
    mt5_password: str
    mt5_server: str
    mt5_path: str | None
    telegram_token: str | None
    telegram_chat_id: str | None
    openai_api_key: str | None


def load_config(path: Path | None = None) -> dict:
    path = path or ROOT / "config" / "config.yaml"
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_secrets() -> Secrets:
    load_dotenv(ROOT / ".env")
    missing = [k for k in ("MT5_LOGIN", "MT5_PASSWORD", "MT5_SERVER") if not os.getenv(k)]
    if missing:
        raise SystemExit(f".env файлд дутуу утга байна: {', '.join(missing)}. "
                         f".env.example-ийг хуулж .env болгоод бөглөнө үү.")
    return Secrets(
        mt5_login=int(os.environ["MT5_LOGIN"]),
        mt5_password=os.environ["MT5_PASSWORD"],
        mt5_server=os.environ["MT5_SERVER"],
        mt5_path=os.getenv("MT5_PATH") or None,
        telegram_token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID") or None,
        openai_api_key=os.getenv("OPENAI_API_KEY") or None,
    )
