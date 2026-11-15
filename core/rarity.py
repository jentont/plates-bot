"""Оценка редкости и стоимости номерных знаков.

Для российских номеров правила подробные (блатные серии, регионы, цифры),
для остальных стран — общие закономерности (повторы, зеркала, короткие номера).
Результат детерминирован: один и тот же номер всегда оценивается одинаково.
"""
from __future__ import annotations

import bisect
import hashlib
import math
import random
import re
from dataclasses import dataclass, field, asdict

from .plates import Plate, generate, COUNTRIES

USD_RATE = 90.0

TIERS = [
    # (нижний порог, ключ, название, цвет)
    (0, "common", "Обычный", "#8E97A8"),
    (12, "uncommon", "Необычный", "#5FB2FF"),
    (28, "rare", "Редкий", "#7C6CFF"),
    (45, "epic", "Эпический", "#E85CFF"),
    (62, "legendary", "Легендарный", "#FFB020"),
    (80, "mythic", "Мифический", "#FF3B3B"),
]

# Известные «блатные» серии: буквы (первая + две последние) -> (очки, пояснение)
RU_SERIES: dict[str, tuple[int, str]] = {
    "АМР": (50, "Серия АМР — федеральные структуры"),
    "ЕКХ": (45, "ЕКХ — «еду как хочу»"),
    "ООО": (42, "Три буквы О"),
    "ААА": (40, "Три буквы А"),
    "ХХХ": (40, "Три буквы Х"),
    "ККК": (38, "Три буквы К"),
    "МММ": (38, "Три буквы М"),
    "ССС": (38, "Три буквы С"),
    "ЕЕЕ": (32, "Три буквы Е"),
    "ННН": (32, "Три буквы Н"),
    "ТТТ": (32, "Три буквы Т"),
    "ВВВ": (32, "Три буквы В"),
    "РРР": (32, "Три буквы Р"),
    "УУУ": (30, "Три буквы У"),
    "ХКХ": (30, "Серия ХКХ"),
    "АОО": (25, "Серия АОО"),
    "АМО": (25, "АМО — мэрия Москвы"),
    "СОО": (22, "Серия СОО"),
    "МОО": (22, "Серия МОО"),
    "КОО": (22, "Серия КОО"),
    "ТОО": (20, "Серия ТОО"),
    "ВОО": (20, "Серия ВОО"),
    "ЕОО": (20, "Серия ЕОО"),
    "НОО": (18, "Серия НОО"),
    "РОО": (18, "Серия РОО"),
    "УОО": (18, "Серия УОО"),
    "ХОО": (18, "Серия ХОО"),
    "ЕРЕ": (20, "Серия ЕРЕ"),
    "ОМР": (20, "Серия ОМР"),
    "ТМР": (18, "Серия ТМР"),
    "КМР": (18, "Серия КМР"),
    "ММР": (18, "Серия ММР"),
    "ВМР": (18, "Серия ВМР"),
    "СМР": (18, "Серия СМР"),
    "УМР": (18, "Серия УМР"),
    "РМР": (18, "Серия РМР"),
    "АСС": (15, "Серия АСС"),
    "АКР": (12, "Серия АКР"),
    "ВОР": (14, "Буквы складываются в слово"),
    "ХАН": (10, "Буквы складываются в слово"),
    "РОК": (8, "Буквы складываются в слово"),
    "ТОР": (6, "Буквы складываются в слово"),
    "МЕХ": (5, "Буквы складываются в слово"),
    "СОН": (5, "Буквы складываются в слово"),
    "ХАМ": (6, "Буквы складываются в слово"),
    "КУМ": (5, "Буквы складываются в слово"),
    "НОС": (5, "Буквы складываются в слово"),
    "СОК": (5, "Буквы складываются в слово"),
    "КОТ": (6, "Буквы складываются в слово"),
    "МАТ": (5, "Буквы складываются в слово"),
}

RU_DIGITS: dict[str, tuple[int, str]] = {
    "777": (45, "Три семёрки"),
    "888": (36, "Три восьмёрки"),
    "999": (34, "Три девятки"),
    "666": (32, "Три шестёрки"),
    "111": (30, "Три единицы"),
    "555": (30, "Три пятёрки"),
    "333": (28, "Три тройки"),
    "222": (26, "Три двойки"),
    "444": (24, "Три четвёрки"),
    "001": (30, "Первый номер серии"),
    "007": (26, "Агент 007"),
    "100": (18, "Круглая сотня"),
    "123": (14, "Последовательность 1-2-3"),
    "321": (12, "Обратный отсчёт"),
    "911": (10, "Номер 911"),
    "112": (6, "Номер 112"),
}

RU_REGION_BONUS: dict[str, tuple[int, str]] = {
    "777": (25, "Регион 777"),
    "77": (12, "Москва"), "97": (12, "Москва"), "99": (12, "Москва"),
    "177": (10, "Москва"), "197": (10, "Москва"), "199": (10, "Москва"),
    "797": (10, "Москва"), "799": (10, "Москва"), "977": (12, "Москва"),
    "78": (10, "Петербург"), "98": (10, "Петербург"), "178": (8, "Петербург"), "198": (8, "Петербург"),
    "95": (8, "Чечня"), "05": (5, "Дагестан"), "06": (4, "Ингушетия"),
    "23": (6, "Краснодар"), "93": (6, "Краснодар"), "123": (6, "Краснодар"),
    "01": (3, "Регион 01"), "02": (2, "Регион 02"), "03": (2, "Регион 03"),
}


@dataclass
class Evaluation:
    score: int
    tier: str
    tier_name: str
    tier_color: str
    price_rub: int
    price_usd: int
    percentile: float                # «топ X%» — доля номеров с не меньшим счётом
    reasons: list[dict] = field(default_factory=list)   # [{"title":..., "points":..., "at": шаг открытия}]
    steps: list = field(default_factory=list)    # [[цена ₽, ключ редкости], ...] после каждого открытого символа
    keys: list = field(default_factory=list)     # что из каталога редкостей есть в номере
    fact: str = ""                               # справка о серии или регионе

    def to_dict(self) -> dict:
        return asdict(self)


def _tier(score: int) -> tuple[str, str, str]:
    key, name, color = TIERS[0][1:]
    for low, k, n, c in TIERS:
        if score >= low:
            key, name, color = k, n, c
    return key, name, color


def _nice(n: float) -> int:
    """Округление к «красивому» числу: 1 234 567 -> 1 200 000."""
    if n <= 0:
        return 0
    mag = 10 ** int(math.log10(n))
    step = mag / 10 if n / mag < 3 else mag / 2
    return int(round(n / step) * step)


def _price_rub(score: int, salt: str) -> int:
    if score < 12:
        return 0
    s = min(score, 100)
    base = 3000 * (1.105 ** s)
    jitter = int(hashlib.md5(salt.encode()).hexdigest()[:4], 16) / 0xFFFF  # 0..1
    base *= 0.88 + 0.24 * jitter
    return _nice(base)


def _digit_patterns(digits: str, reasons: list, strong: bool = True) -> int:
    """Общие закономерности для группы цифр любой страны."""
    pts = 0
    if not digits:
        return 0
    n = len(digits)
    if len(set(digits)) == 1 and n >= 3:
        p = {3: 28, 4: 36, 5: 44}.get(n, 48)
        if digits[0] in "78":
            p += 6
        pts += p
        reasons.append({"title": f"Все цифры одинаковые: {digits}", "points": p})
    elif digits in ("123", "1234", "12345", "321", "4321", "54321"):
        pts += 16
        reasons.append({"title": "Последовательность цифр", "points": 16})
    elif digits == digits[::-1] and n >= 3:
        pts += 8
        reasons.append({"title": "Зеркальные цифры", "points": 8})
    elif n >= 3 and (digits[0] == digits[1] or digits[-1] == digits[-2]):
        pts += 4
        reasons.append({"title": "Пара одинаковых цифр", "points": 4})
    if n >= 3 and digits.lstrip("0") in ("1", "7"):
        pts += 24
        reasons.append({"title": f"Номер {int(digits)} в серии", "points": 24})
    elif n >= 3 and int(digits) <= 9 and int(digits) > 0:
        pts += 14
        reasons.append({"title": "Номер до десяти", "points": 14})
    elif n >= 3 and int(digits) % 100 == 0 and int(digits) > 0:
        pts += 12
        reasons.append({"title": "Круглое число", "points": 12})
    return pts


# Порядок открытия символов российского номера: буква, три цифры, две буквы, регион.
# Шаг k означает «открыто k+1 символов».
RU_AT_DIGITS, RU_AT_L2, RU_AT_L3 = 3, 4, 5


def _evaluate_ru(plate: Plate) -> tuple[int, list[dict]]:
    p = plate.parts
    letters = p["l1"] + p["l2"] + p["l3"]
    digits = p["digits"]
    region = p["region"]
    last = 5 + len(region)
    reasons: list[dict] = []
    score = 0

    def add(title: str, pts: int, at: int, key: str) -> None:
        nonlocal score
        score += pts
        reasons.append({"title": title, "points": pts, "at": at, "key": key})

    # Буквы (видны, когда открыта последняя буква серии)
    if letters in RU_SERIES:
        pts, title = RU_SERIES[letters]
        add(title, pts, RU_AT_L3, "s:" + letters)
    elif p["l2"] == p["l3"]:
        add(f"Парные буквы {p['l2']}{p['l3']}", 10, RU_AT_L3, "g:letters2")
    elif p["l1"] == p["l2"] or p["l1"] == p["l3"]:
        add("Повтор буквы", 4, RU_AT_L2 if p["l1"] == p["l2"] else RU_AT_L3, "g:letter")

    # Цифры (видны после третьей цифры)
    if digits in RU_DIGITS:
        pts, title = RU_DIGITS[digits]
        add(title, pts, RU_AT_DIGITS, "d:" + digits)
    elif int(digits) % 100 == 0:
        add(f"Круглые цифры {digits}", 15, RU_AT_DIGITS, "g:round")
    elif int(digits) < 10:
        add("Номер до десяти", 16, RU_AT_DIGITS, "g:under10")
    elif digits == digits[::-1]:
        add("Зеркальные цифры", 8, RU_AT_DIGITS, "g:mirror")
    elif digits[0] == digits[1] or digits[1] == digits[2]:
        add("Пара одинаковых цифр", 5, RU_AT_DIGITS, "g:pair")

    # Регион
    if region in RU_REGION_BONUS:
        pts, title = RU_REGION_BONUS[region]
        add(title, pts, last, "r:" + title)

    # Комбинации
    if digits == region:
        add("Цифры совпадают с регионом", 20, last, "c:region")
    if digits == "777" and region == "777":
        add("Джекпот: 777 в регионе 777", 30, last, "c:jackpot")
    if len(set(letters)) == 1 and len(set(digits)) == 1:
        add("Полный комплект: буквы и цифры", 20, last, "c:full")
    elif letters in RU_SERIES and RU_SERIES[letters][0] >= 20 and digits in RU_DIGITS:
        add("Блатная серия с красивыми цифрами", 10, last, "c:blat")

    return score, reasons


def _evaluate_generic(plate: Plate) -> tuple[int, list[dict]]:
    reasons: list[dict] = []
    score = 0
    text = plate.text
    digit_groups = re.findall(r"\d+", text)
    letter_groups = re.findall(r"[A-ZА-ЯЁ]{2,}", text)

    if plate.country == "AE":
        n = len(plate.parts.get("num", ""))
        pts = {1: 70, 2: 50, 3: 32, 4: 14}.get(n, 0)
        if pts:
            score += pts
            reasons.append({"title": f"Короткий номер: {n} цифр", "points": pts})
        if plate.parts.get("emirate") == "Dubai":
            score += 5
            reasons.append({"title": "Дубай", "points": 5})
        for g in digit_groups:
            score += _digit_patterns(g, reasons) if len(g) >= 3 else 0
        return score, reasons

    if plate.country == "JP":
        num = plate.parts.get("num", "").replace("-", "")
        score += _digit_patterns(num, reasons)
        if num[:2] == num[2:]:
            score += 10
            reasons.append({"title": "Повторяющаяся пара", "points": 10})
        if plate.parts.get("office") in ("品川", "横浜"):
            score += 6
            reasons.append({"title": "Престижный округ", "points": 6})
        return score, reasons

    if plate.country == "CN":
        tail = plate.parts.get("tail", "")
        if tail.isdigit():
            score += _digit_patterns(tail, reasons)
        if "8" in tail and tail.count("8") >= 3:
            score += 18
            reasons.append({"title": "Много восьмёрок — удача", "points": 18})
        if plate.parts.get("letter") == "A":
            score += 8
            reasons.append({"title": "Серия A — столичная", "points": 8})
        return score, reasons

    for g in digit_groups:
        if len(g) >= 3:
            score += _digit_patterns(g, reasons)
    if len(digit_groups) >= 2 and len({g for g in digit_groups if len(g) >= 2}) == 1:
        score += 12
        reasons.append({"title": "Числа повторяются", "points": 12})

    for g in letter_groups:
        if len(g) >= 2 and len(set(g)) == 1:
            pts = 10 if len(g) == 2 else 25
            score += pts
            reasons.append({"title": f"Одинаковые буквы {g}", "points": pts})
    if len(letter_groups) >= 2 and letter_groups[0] == letter_groups[-1]:
        score += 10
        reasons.append({"title": "Буквы повторяются", "points": 10})

    region_bonus = {
        "UA": {"AA": (10, "Киев"), "KA": (10, "Киев")},
        "DE": {"B": (6, "Берлин"), "M": (6, "Мюнхен"), "HH": (5, "Гамбург")},
        "US": {"CA": (6, "Калифорния"), "NY": (6, "Нью-Йорк"), "NV": (4, "Невада")},
        "KZ": {"01": (8, "Астана"), "02": (8, "Алматы")},
        "BY": {"7": (6, "Минск")},
        "UZ": {"01": (8, "Ташкент")},
        "AM": {"01": (6, "Ереван")},
        "TR": {"34": (6, "Стамбул"), "06": (4, "Анкара")},
        "PL": {"WA": (5, "Варшава")},
    }.get(plate.country, {})
    if plate.region in region_bonus:
        pts, title = region_bonus[plate.region]
        score += pts
        reasons.append({"title": title, "points": pts})
    return score, reasons


def reveal_len(plate: Plate) -> int:
    """Сколько символов открывается по одному. Мини-апа открывает их в том же порядке и том же количестве."""
    if plate.country == "RU":
        return 6 + len(plate.parts["region"])
    return sum(1 for ch in plate.text if ch != " ")


def _steps(plate: Plate, reasons: list[dict], price_rub: int, tier: str) -> list:
    """Цена и редкость после каждого открытого символа. Растут только тогда, когда закономерность уже видна."""
    n = reveal_len(plate)
    out = []
    for k in range(n):
        sc = sum(r["points"] for r in reasons if r.get("at", n - 1) <= k)
        out.append([_price_rub(sc, plate.text), _tier(sc)[0]])
    if out:
        out[-1] = [price_rub, tier]          # последний шаг всегда равен итогу
    return out


def evaluate(plate: Plate) -> Evaluation:
    if plate.country == "RU":
        score, reasons = _evaluate_ru(plate)
    else:
        score, reasons = _evaluate_generic(plate)
    score = max(0, score)
    key, name, color = _tier(score)
    price_rub = _price_rub(score, plate.text)
    price_usd = _nice(price_rub / USD_RATE) if price_rub else 0
    keys = [r.pop("key") for r in reasons if "key" in r]
    if not reasons:
        reasons.append({"title": "Без особых признаков", "points": 0})
    return Evaluation(
        score=score, tier=key, tier_name=name, tier_color=color,
        price_rub=price_rub, price_usd=price_usd,
        percentile=percentile(plate.country, score), reasons=reasons,
        steps=_steps(plate, reasons, price_rub, key), keys=keys, fact=fact_of(plate),
    )


# ---------------------------------------------------------------- Справки и каталог

#: Справка под номером. Только то, что широко известно, без выдумок.
SERIES_FACTS: dict[str, str] = {
    "АМР": "Серию связывают с машинами федеральных ведомств. На вторичном рынке одна из самых дорогих",
    "ЕКХ": "В народе «еду как хочу». Считалась серией спецслужб, сейчас во многом у частников",
    "ААА": "Три одинаковые буквы видно издалека. Одна из самых узнаваемых серий",
    "ООО": "Три «О» на дороге читаются как три нуля. За такие серии на рынке просят миллионы",
    "ХХХ": "Три «Х» встречаются на дороге редко, и их любят за дерзость",
    "АМО": "Серию связывают с машинами московской мэрии",
    "ХКХ": "Перевёртыш: серия читается одинаково с обеих сторон",
    "ЕРЕ": "Перевёртыш: серия читается одинаково с обеих сторон",
    "ВОР": "Номер-шутка. Такие покупают ради надписи, а не ради статуса",
}
DIGIT_FACTS: dict[str, str] = {
    "777": "Три семёрки — самые желанные цифры на российских номерах",
    "001": "Первый номер серии: в каждой серии региона такой только один",
    "007": "«Агентский» номер, его ищут поклонники Бонда",
}
REGION_FACTS: dict[str, str] = {
    "777": "Регион 777 — московский, один из самых узнаваемых в стране",
    "77": "Регион 77 — первый московский код, самый статусный из московских",
    "97": "Ранние московские коды ценятся выше поздних трёхзначных",
    "99": "Ранние московские коды ценятся выше поздних трёхзначных",
    "78": "Регион 78 — Санкт-Петербург",
    "95": "Регион 95 — Чечня. Красивые номера там в большом почёте",
}


def fact_of(plate: Plate) -> str:
    if plate.country != "RU":
        return ""
    p = plate.parts
    return (SERIES_FACTS.get(p["l1"] + p["l2"] + p["l3"]) or DIGIT_FACTS.get(p["digits"])
            or REGION_FACTS.get(p["region"]) or "")


CATALOG_GROUPS = {"c": "Комбинации", "s": "Серии букв", "d": "Цифры", "r": "Регионы", "g": "Закономерности"}


def catalog() -> list[dict]:
    """Каталог редкостей российского номера. Ключи совпадают с Evaluation.keys."""
    items = [{"key": "c:jackpot", "title": "Джекпот: 777 в регионе 777", "points": 30, "example": "А777АА 777"},
             {"key": "c:full", "title": "Полный комплект: буквы и цифры", "points": 20, "example": "М555ММ 50"},
             {"key": "c:region", "title": "Цифры совпадают с регионом", "points": 20, "example": "К199РУ 199"},
             {"key": "c:blat", "title": "Блатная серия с красивыми цифрами", "points": 10, "example": "А777МР 97"}]
    for letters, (pts, title) in sorted(RU_SERIES.items(), key=lambda kv: -kv[1][0]):
        items.append({"key": "s:" + letters, "title": f"Слово {letters}" if title.startswith("Буквы") else title,
                      "points": pts, "example": f"{letters[0]}123{letters[1:]} 50"})
    for digits, (pts, title) in sorted(RU_DIGITS.items(), key=lambda kv: -kv[1][0]):
        items.append({"key": "d:" + digits, "title": title, "points": pts, "example": f"В{digits}ОР 50"})
    seen = set()
    for code, (pts, title) in sorted(RU_REGION_BONUS.items(), key=lambda kv: -kv[1][0]):
        if title not in seen:
            seen.add(title)
            items.append({"key": "r:" + title, "title": title, "points": pts, "example": f"В123ОР {code}"})
    items += [{"key": "g:under10", "title": "Номер до десяти", "points": 16, "example": "В005ОР 50"},
              {"key": "g:round", "title": "Круглые цифры", "points": 15, "example": "В200ОР 50"},
              {"key": "g:letters2", "title": "Парные буквы", "points": 10, "example": "Р123ТТ 50"},
              {"key": "g:mirror", "title": "Зеркальные цифры", "points": 8, "example": "В353ОР 50"},
              {"key": "g:pair", "title": "Пара одинаковых цифр", "points": 5, "example": "В332ОР 50"},
              {"key": "g:letter", "title": "Повтор буквы", "points": 4, "example": "В123ВР 50"}]
    for it in items:
        it["group"] = CATALOG_GROUPS[it["key"][0]]
    return items


# ---------------------------------------------------------------- Распределение

_DIST: dict[str, list[int]] = {}
DIST_FILE = __import__("pathlib").Path(__file__).with_name("distribution.json")
SAMPLES = 20000


def build_distribution(country: str) -> list[int]:
    rng = random.Random(1309)
    return sorted(evaluate_score_only(generate(country, rng)) for _ in range(SAMPLES))


def _load_file() -> None:
    """Распределения считаются заранее (tools/make_distribution.py) — на слабом сервере
    генерация 20 000 номеров на страну занимала секунды и подвешивала всех игроков."""
    import json
    try:
        data = json.loads(DIST_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    for country, pairs in data.items():       # [[очки, сколько раз], ...] → отсортированный список
        _DIST[country] = [score for score, count in pairs for _ in range(count)]


def _distribution(country: str) -> list[int]:
    if not _DIST:
        _load_file()
    if country not in _DIST:
        _DIST[country] = build_distribution(country)
    return _DIST[country]


def evaluate_score_only(plate: Plate) -> int:
    if plate.country == "RU":
        return max(0, _evaluate_ru(plate)[0])
    return max(0, _evaluate_generic(plate)[0])


def percentile(country: str, score: int) -> float:
    """Доля номеров (в процентах) со счётом не меньше данного: «топ 3.2%»."""
    dist = _distribution(country if country in COUNTRIES else "RU")
    idx = bisect.bisect_left(dist, score)
    top = (len(dist) - idx) / len(dist) * 100
    return round(max(top, 0.01), 1)


def format_price(ev: Evaluation, country: str) -> str:
    if ev.price_rub == 0:
        return "0 ₽" if country == "RU" else "$0"
    if country == "RU":
        return f"{ev.price_rub:,} ₽".replace(",", " ")
    return f"${ev.price_usd:,}".replace(",", " ")
