"""Прогресс игрока: ежедневные задания, достижения, кейсы, улучшения, коллекция, статистика.

Все награды и покупки атомарны: награда пишется в claims с первичным ключом, поэтому
двойное нажатие не даёт её дважды; деньги списываются условием money>=цена в одном UPDATE.

Экономика: деньги ничем не превращаются обратно в энергию (её покупают за Stars), поэтому
задания и достижения дают в основном деньги, а энергию — понемногу и раз в день.
"""
from __future__ import annotations

import random
import time

from core.cars import CARS, plate_money
from core.plates import generate
from core.rarity import TIERS, catalog, evaluate

from .storage import Storage

TIER_RANK = {k: i for i, (_, k, _, _) in enumerate(TIERS)}
MSK = 3 * 3600


def day_start(now: float | None = None) -> float:
    """Начало текущих суток по Москве (задания обновляются в полночь МСК)."""
    now = time.time() if now is None else now
    return (now + MSK) // 86400 * 86400 - MSK


# ------------------------------------------------------------ задания

#: id, текст, метрика за сегодня, цель, награда (money|energy, сколько)
TASKS = [
    {"id": "spin20", "title": "Прокрути 20 номеров", "metric": "spins", "goal": 20, "reward": ["money", 50_000]},
    {"id": "spin100", "title": "Прокрути 100 номеров", "metric": "spins", "goal": 100, "reward": ["energy", 10]},
    {"id": "rare", "title": "Выбей редкий номер или лучше", "metric": "best", "goal": 28, "reward": ["money", 200_000]},
    {"id": "save", "title": "Сохрани номер в гараж", "metric": "saved", "goal": 1, "reward": ["money", 20_000]},
    {"id": "sell5", "title": "Продай 5 номеров", "metric": "sold", "goal": 5, "reward": ["money", 40_000]},
    {"id": "case", "title": "Открой кейс", "metric": "cases", "goal": 1, "reward": ["money", 60_000]},
]

# ------------------------------------------------------------ достижения

ACHIEVEMENTS = [
    {"id": "spins10", "title": "Первые шаги", "text": "Прокрути 10 номеров", "metric": "spins", "goal": 10, "reward": 10_000},
    {"id": "spins100", "title": "Втянулся", "text": "Прокрути 100 номеров", "metric": "spins", "goal": 100, "reward": 50_000},
    {"id": "spins1000", "title": "Завсегдатай", "text": "Прокрути 1 000 номеров", "metric": "spins", "goal": 1000, "reward": 500_000},
    {"id": "spins10000", "title": "Легенда ГИБДД", "text": "Прокрути 10 000 номеров", "metric": "spins", "goal": 10000, "reward": 5_000_000},
    {"id": "tier_uncommon", "title": "Не как все", "text": "Выбей необычный номер", "metric": "best", "goal": 12, "reward": 10_000},
    {"id": "tier_rare", "title": "Редкая птица", "text": "Выбей редкий номер", "metric": "best", "goal": 28, "reward": 100_000},
    {"id": "tier_epic", "title": "Эпично", "text": "Выбей эпический номер", "metric": "best", "goal": 45, "reward": 500_000},
    {"id": "tier_legendary", "title": "Блатной", "text": "Выбей легендарный номер", "metric": "best", "goal": 62, "reward": 3_000_000},
    {"id": "tier_mythic", "title": "Миф", "text": "Выбей мифический номер", "metric": "best", "goal": 80, "reward": 20_000_000},
    {"id": "sold10", "title": "Перекупщик", "text": "Продай 10 номеров", "metric": "sold", "goal": 10, "reward": 50_000},
    {"id": "sold100", "title": "Барыга", "text": "Продай 100 номеров", "metric": "sold", "goal": 100, "reward": 500_000},
    {"id": "car1", "title": "Права получены", "text": "Купи первую машину", "metric": "cars", "goal": 1, "reward": 100_000},
    {"id": "car5", "title": "Автопарк", "text": "Купи 5 машин", "metric": "cars", "goal": 5, "reward": 2_000_000},
    {"id": "carall", "title": "Весь автосалон", "text": f"Купи все {len(CARS)} машин", "metric": "cars", "goal": len(CARS), "reward": 30_000_000},
    {"id": "finds10", "title": "Коллекционер", "text": "Собери 10 редкостей из каталога", "metric": "finds", "goal": 10, "reward": 200_000},
    {"id": "finds30", "title": "Знаток номеров", "text": "Собери 30 редкостей из каталога", "metric": "finds", "goal": 30, "reward": 1_500_000},
    {"id": "earned10m", "title": "Миллионер", "text": "Заработай 10 000 000 ₽ на продаже", "metric": "earned", "goal": 10_000_000, "reward": 1_000_000},
]

# ------------------------------------------------------------ кейсы

#: Номер из кейса не хуже порога. Средняя выручка с номера (case_ev) ~60 000 / 290 000 / 1 230 000 ₽,
#: цена примерно в полтора раза выше: кейс — ставка на удачу, а не печатный станок.
CASES = [
    {"id": "silver", "title": "Серебряный кейс", "min": 12, "price": 80_000, "text": "Номер не хуже необычного"},
    {"id": "gold", "title": "Золотой кейс", "min": 28, "price": 450_000, "text": "Номер не хуже редкого"},
    {"id": "black", "title": "Чёрный кейс", "min": 45, "price": 1_900_000, "text": "Номер не хуже эпического"},
]
CASE_BY_ID = {c["id"]: c for c in CASES}

# ------------------------------------------------------------ улучшения

SLOT_STEP, SLOT_LEVELS, SLOT_BASE = 5, 6, 250_000
AUTO_PRICE, AUTOSELL_PRICE = 500_000, 300_000


def slot_price(level: int) -> int:
    return SLOT_BASE * 3 ** level


class Progress:
    def __init__(self, storage: Storage, rng: random.Random | None = None):
        self.st = storage
        self.rng = rng or random.SystemRandom()
        self.catalog = catalog()

    # ---------------------------------------------------- метрики
    def _one(self, sql: str, *a):
        return self.st.db.execute(sql, a).fetchone()[0]

    def today(self, uid: int) -> dict:
        d = day_start()
        return {
            "spins": self._one("SELECT COUNT(*) FROM rolls WHERE user_id=? AND created>=? AND source!='case'", uid, d),
            "best": self._one("SELECT COALESCE(MAX(score), 0) FROM rolls WHERE user_id=? AND created>=?", uid, d),
            "saved": self._one("SELECT COUNT(*) FROM rolls WHERE user_id=? AND created>=? AND saved=1", uid, d),
            "sold": self._one("SELECT COUNT(*) FROM rolls WHERE user_id=? AND sold_ts>=?", uid, d),
            "cases": self._one("SELECT COUNT(*) FROM rolls WHERE user_id=? AND created>=? AND source='case'", uid, d),
        }

    def lifetime(self, uid: int) -> dict:
        row = self.st.db.execute("SELECT spins, best_score, sold_count, earned FROM users WHERE id=?", (uid,)).fetchone()
        return {"spins": row["spins"], "best": row["best_score"], "sold": row["sold_count"], "earned": row["earned"],
                "cars": self._one("SELECT COUNT(*) FROM user_cars WHERE user_id=?", uid),
                "finds": self._one("SELECT COUNT(*) FROM finds WHERE user_id=?", uid)}

    def _claimed(self, uid: int, prefix: str) -> set[str]:
        return {r[0] for r in self.st.db.execute("SELECT key FROM claims WHERE user_id=? AND key LIKE ?", (uid, prefix + "%"))}

    # ---------------------------------------------------- задания
    def tasks(self, uid: int) -> dict:
        d = int(day_start())
        prefix = f"t:{d}:"
        got, done = self.today(uid), self._claimed(uid, prefix)
        items = [{**t, "progress": min(got[t["metric"]], t["goal"]), "done": got[t["metric"]] >= t["goal"],
                  "claimed": prefix + t["id"] in done} for t in TASKS]
        return {"items": items, "resets_in": int(d + 86400 - time.time())}

    def achievements(self, uid: int) -> list[dict]:
        got, done = self.lifetime(uid), self._claimed(uid, "a:")
        return [{**a, "progress": min(got[a["metric"]], a["goal"]), "done": got[a["metric"]] >= a["goal"],
                 "claimed": "a:" + a["id"] in done} for a in ACHIEVEMENTS]

    def claim(self, uid: int, kind: str, item_id: str) -> tuple[str, dict | None]:
        """kind: task | ach. Возвращает ('ok'|'missing'|'not_done'|'claimed', награда)."""
        if kind == "task":
            item = next((t for t in self.tasks(uid)["items"] if t["id"] == item_id), None)
            key = f"t:{int(day_start())}:{item_id}"
            reward = item and {"kind": item["reward"][0], "amount": item["reward"][1]}
        else:
            item = next((a for a in self.achievements(uid) if a["id"] == item_id), None)
            key = "a:" + item_id
            reward = item and {"kind": "money", "amount": item["reward"]}
        if not item:
            return "missing", None
        if not item["done"]:
            return "not_done", None
        with self.st.lock:
            cur = self.st.db.execute("INSERT OR IGNORE INTO claims(user_id, key, ts) VALUES (?,?,?)", (uid, key, time.time()))
            if not cur.rowcount:
                return "claimed", None
            if reward["kind"] == "money":
                self.st.db.execute("UPDATE users SET money=money+? WHERE id=?", (reward["amount"], uid))
            self.st.db.commit()
        if reward["kind"] == "energy":
            self.st.add_energy(uid, reward["amount"])
        return "ok", reward

    def badge(self, uid: int) -> int:
        """Сколько наград можно забрать прямо сейчас (точка на вкладке «Меню»)."""
        return (sum(1 for t in self.tasks(uid)["items"] if t["done"] and not t["claimed"])
                + sum(1 for a in self.achievements(uid) if a["done"] and not a["claimed"]))

    # ---------------------------------------------------- деньги
    def _spend(self, uid: int, price: int, extra_sql: str = "", extra_args: tuple = ()) -> bool:
        """Списать деньги и одним же запросом применить покупку. False — не хватает."""
        with self.st.lock:
            cur = self.st.db.execute(f"UPDATE users SET money=money-?{extra_sql} WHERE id=? AND money>=?",
                                     (price, *extra_args, uid, price))
            self.st.db.commit()
            return bool(cur.rowcount)

    # ---------------------------------------------------- кейсы
    def case_plate(self, min_score: int):
        """Российский номер не хуже порога: выбрасываем, пока не выпадет подходящий."""
        best = None
        for _ in range(40_000):
            plate = generate("RU", self.rng)
            ev = evaluate(plate)
            if ev.score >= min_score:
                return plate, ev
            if best is None or ev.score > best[1].score:
                best = (plate, ev)
        return best

    def open_case(self, uid: int, case_id: str) -> tuple[str, dict | None]:
        case = CASE_BY_ID.get(case_id)
        if not case:
            return "missing", None
        plate, ev = self.case_plate(case["min"])   # номер выбираем до списания: если что-то упадёт, деньги целы
        if not self._spend(uid, case["price"]):
            return "poor", None
        return "ok", self.st.add_roll(uid, plate, ev, "case")

    # ---------------------------------------------------- улучшения
    def upgrades(self, uid: int) -> dict:
        row = self.st.db.execute("SELECT extra_slots, auto_owned, autosell_owned, autosell FROM users WHERE id=?", (uid,)).fetchone()
        level = min(SLOT_LEVELS, row["extra_slots"] // SLOT_STEP)
        return {
            "slots": {"level": level, "max": SLOT_LEVELS, "step": SLOT_STEP,
                      "price": slot_price(level) if level < SLOT_LEVELS else 0,
                      "total": self.st.stats(uid)["slots"]},
            "auto": {"owned": bool(row["auto_owned"]), "price": AUTO_PRICE},
            "autosell": {"owned": bool(row["autosell_owned"]), "price": AUTOSELL_PRICE, "below": row["autosell"] or ""},
        }

    def buy_upgrade(self, uid: int, what: str) -> str:
        up = self.upgrades(uid)
        if what == "slots":
            if up["slots"]["level"] >= SLOT_LEVELS:
                return "max"
            ok = self._spend(uid, up["slots"]["price"], ", extra_slots=extra_slots+?", (SLOT_STEP,))
        elif what in ("auto", "autosell"):
            if up[what]["owned"]:
                return "owned"
            price = AUTO_PRICE if what == "auto" else AUTOSELL_PRICE
            ok = self._spend(uid, price, f", {what}_owned=1")
            if ok and what == "autosell":
                self.set_autosell(uid, "uncommon")      # сразу включаем: продавать обычные
        else:
            return "missing"
        return "ok" if ok else "poor"

    def set_autosell(self, uid: int, below: str) -> bool:
        """Продавать за деньги всё, что ниже редкости below. Пустая строка — выключить."""
        if below and below not in TIER_RANK:
            return False
        with self.st.lock:
            cur = self.st.db.execute("UPDATE users SET autosell=? WHERE id=? AND autosell_owned=1", (below, uid))
            self.st.db.commit()
            return bool(cur.rowcount)

    def autosell_after_spin(self, uid: int, roll: dict, money_price) -> int:
        """Если номер ниже порога автопродажи — сразу продаёт его за деньги. Возвращает выручку или 0."""
        row = self.st.db.execute("SELECT autosell_owned, autosell FROM users WHERE id=?", (uid,)).fetchone()
        below = row["autosell"] if row and row["autosell_owned"] else ""
        if not below or TIER_RANK.get(roll["eval"]["tier"], 0) >= TIER_RANK[below]:
            return 0
        status, _, gain = self.st.sell_roll(roll["id"], uid, money_price, True)
        return gain if status == "ok" else 0

    # ---------------------------------------------------- коллекция и статистика
    def collection(self, uid: int) -> dict:
        found = {r["key"]: {"count": r["count"], "first": r["first"]}
                 for r in self.st.db.execute("SELECT key, count, first FROM finds WHERE user_id=?", (uid,))}
        items = [{**c, **found.get(c["key"], {"count": 0})} for c in self.catalog]
        return {"items": items, "found": sum(1 for i in items if i["count"]), "total": len(items)}

    def stats(self, uid: int) -> dict:
        life = self.lifetime(uid)
        tiers = {r["tier"]: r["count"] for r in self.st.db.execute("SELECT tier, count FROM tier_counts WHERE user_id=?", (uid,))}
        row = self.st.db.execute("SELECT money, created FROM users WHERE id=?", (uid,)).fetchone()
        return {**life, "money": row["money"], "days": int((time.time() - row["created"]) // 86400) + 1,
                "tiers": [{"tier": k, "name": n, "color": c, "count": tiers.get(k, 0)} for _, k, n, c in TIERS],
                "catalog_total": len(self.catalog)}


def case_ev(min_score: int, samples: int = 400, seed: int = 7) -> float:
    """Средняя выручка с номера из кейса при продаже за деньги (для подбора цены кейса)."""
    p = Progress.__new__(Progress)
    p.rng = random.Random(seed)
    total = 0
    for _ in range(samples):
        plate, ev = p.case_plate(min_score)
        total += plate_money({"eval": ev.to_dict(), "plate": plate.to_dict()})
    return total / samples
