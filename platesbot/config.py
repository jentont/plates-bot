"""Настройки из переменных окружения (или файла .env рядом с проектом)."""
from __future__ import annotations

import json
import os
import sys
import time
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


#: Сколько прокрутов бот даёт за номер каждой редкости. Обычные не выкупаются:
#: ожидаемая выручка с броска (~0.3) должна быть меньше его цены (1), иначе энергия бесконечна.
DEFAULT_SELL_PRICES = {"common": 0, "uncommon": 1, "rare": 3, "epic": 10, "legendary": 40, "mythic": 150}


def _sell_prices() -> dict:
    prices = dict(DEFAULT_SELL_PRICES)
    raw = os.environ.get("SELL_PRICES", "").strip()
    if raw:
        try:
            for k, v in json.loads(raw).items():
                if k in prices and int(v) >= 0:
                    prices[k] = int(v)
        except (ValueError, TypeError, AttributeError):
            pass
    return prices


PERSISTENT_DIRS = ("/data", "/var/data", "/persistent")


def _db_path() -> Path:
    """Где лежит база: DATA_DIR → DB_PATH → data/ рядом с кодом (на Bothost это /app/data — постоянная папка).

    Если база раньше лежала в /data или похожей папке, а в data/ её нет, — один раз переносим её оттуда.
    """
    if os.environ.get("DATA_DIR"):
        return Path(os.environ["DATA_DIR"]) / "plates.db"
    if os.environ.get("DB_PATH"):
        return ROOT / os.environ["DB_PATH"]
    main = ROOT / "data" / "plates.db"
    if not main.exists():
        for d in PERSISTENT_DIRS:
            old = Path(d) / "plates.db"
            if old.exists() and old.stat().st_size > 0:
                try:
                    main.parent.mkdir(parents=True, exist_ok=True)
                    main.write_bytes(old.read_bytes())
                except OSError:
                    return old
                break
    return main


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
    db_path: Path = field(default_factory=lambda: _db_path())
    energy_max: int = _int("ENERGY_MAX", 30)
    energy_regen_sec: int = _int("ENERGY_REGEN_SEC", 90)
    garage_free_slots: int = _int("GARAGE_FREE_SLOTS", 5)
    stars_forever: int = _int("STARS_FOREVER", 10)                     # 0 — отключить покупку «навсегда»
    roll_ttl_sec: int = _int("ROLL_TTL_SEC", 86400)
    feed_interval: float = float(os.environ.get("FEED_INTERVAL", "1.0"))
    admin_ids: tuple = _ids(os.environ.get("ADMIN_IDS", ""))                # кто видит /admin
    backup_chat: str = os.environ.get("BACKUP_CHAT", "").strip()           # куда слать бэкап базы (иначе личка админа)
    backup_every: int = _int("BACKUP_EVERY", 900)                       # как часто, сек (только если база менялась)
    storage_chat: str = os.environ.get("STORAGE_CHAT", "").strip()         # склад картинок (id канала/группы)
    group_nudge_every: int = _int("GROUP_NUDGE_EVERY", 100)              # напоминание «.ролл» в группах, 0 — выкл
    sell_prices: dict = field(default_factory=_sell_prices)              # выкуп номеров за прокруты

    def sell_price(self, roll: dict) -> int:
        """Сколько прокрутов дадут за номер. 0 — не выкупается или уже продан/сгорел."""
        if roll.get("sold"):
            return 0
        if not roll.get("saved") and not roll.get("forever") and roll.get("expires", 0) < time.time():
            return 0
        return int(self.sell_prices.get(roll["eval"]["tier"], 0))

    def money_price(self, roll: dict) -> int:
        """Сколько рублей дадут за номер. 0 — уже продан или сгорел."""
        if roll.get("sold"):
            return 0
        if not roll.get("saved") and not roll.get("forever") and roll.get("expires", 0) < time.time():
            return 0
        from core.cars import plate_money
        return plate_money(roll)
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
