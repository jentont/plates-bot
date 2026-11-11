"""Настройки из переменных окружения (или файла .env рядом с проектом)."""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv(ROOT / ".env")


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


DEFAULT_ENERGY_PACKS = [
    {"id": "s", "amount": 30, "stars": 15},
    {"id": "m", "amount": 100, "stars": 40},
    {"id": "l", "amount": 300, "stars": 100},
]


def _energy_packs() -> list[dict]:
    """Наборы энергии за Stars: ENERGY_PACKS (JSON-список) или значения по умолчанию."""
    default = [dict(p) for p in DEFAULT_ENERGY_PACKS]
    raw = os.environ.get("ENERGY_PACKS", "").strip()
    if not raw:
        return default
    try:
        packs, seen = [], set()
        for p in json.loads(raw):
            pack = {"id": str(p["id"]), "amount": int(p["amount"]), "stars": int(p["stars"])}
            # id уходит в callback_data и payload счёта, поэтому только короткий и без двоеточий
            if (not pack["id"] or ":" in pack["id"] or len(pack["id"]) > 32 or pack["id"] in seen
                    or pack["amount"] <= 0 or pack["stars"] <= 0):
                return default
            seen.add(pack["id"])
            packs.append(pack)
        return packs or default
    except (ValueError, TypeError, KeyError):
        return default


def _ids(raw: str) -> tuple[int, ...]:
    return tuple(int(x) for x in raw.replace(";", ",").split(",") if x.strip().lstrip("-").isdigit())


@dataclass(frozen=True)
class Config:
    bot_token: str = os.environ.get("BOT_TOKEN", "")
    public_url: str = os.environ.get("PUBLIC_URL", "").rstrip("/")   # https-адрес сервера (мини-апа, карточки)
    host: str = os.environ.get("HOST", "0.0.0.0")
    port: int = _int("PORT", 8080)
    dev_mode: bool = os.environ.get("DEV_MODE", "0") == "1" or "--dev" in sys.argv   # мини-апа без initData
    # DATA_DIR — постоянная папка хостинга: без неё база внутри контейнера стирается при каждом обновлении
    db_path: Path = (Path(os.environ["DATA_DIR"]) / "plates.db") if os.environ.get("DATA_DIR") else ROOT / os.environ.get("DB_PATH", "data/plates.db")
    energy_max: int = _int("ENERGY_MAX", 30)
    energy_regen_sec: int = _int("ENERGY_REGEN_SEC", 90)
    garage_free_slots: int = _int("GARAGE_FREE_SLOTS", 5)
    stars_forever: int = _int("STARS_FOREVER", 10)                     # 0 — отключить покупку «навсегда»
    roll_ttl_sec: int = _int("ROLL_TTL_SEC", 86400)
    feed_interval: float = float(os.environ.get("FEED_INTERVAL", "1.0"))
    admin_ids: tuple = _ids(os.environ.get("ADMIN_IDS", ""))                # кто видит /admin
    subscribe_ttl: int = _int("SUBSCRIBE_TTL", 600)                      # сколько верим проверке подписки
    report_hour: int = _int("REPORT_HOUR", 21)                           # отчёт по спонсорам, час по Москве
    icon_packs: tuple = tuple(x.strip() for x in os.environ.get("ICON_PACKS", "tgiosicons").split(",") if x.strip())
    anthropic_api_key: str = os.environ.get("ANTHROPIC_API_KEY", "")
    ai_model: str = os.environ.get("AI_MODEL", "claude-opus-5-5")
    energy_packs: list = field(default_factory=_energy_packs)          # наборы энергии за Stars

    def energy_pack(self, pack_id) -> dict | None:
        return next((p for p in self.energy_packs if p["id"] == pack_id), None)

    @property
    def ai_enabled(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def webapp_url(self) -> str:
        return self.public_url + "/" if self.public_url else ""


config = Config()
