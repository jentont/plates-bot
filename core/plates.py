"""Генерация номерных знаков разных стран.

Каждая страна описана функцией-генератором, которая возвращает Plate.
Внешний вид (цвета, флаг, компоновка) описан в поле style и повторяется
в мини-апе (webapp/app.js) и в рендере карточек (bot/render.py).
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field, asdict
from typing import Callable

RU_LETTERS = "АВЕКМНОРСТУХ"

# Код региона -> (название, вес выпадения). Вес примерно пропорционален автопарку.
RU_REGIONS: dict[str, tuple[str, float]] = {
    "01": ("Адыгея", 0.3), "02": ("Башкортостан", 2.5), "102": ("Башкортостан", 1.5),
    "03": ("Бурятия", 0.6), "04": ("Алтай", 0.2), "05": ("Дагестан", 1.8),
    "06": ("Ингушетия", 0.3), "07": ("Кабардино-Балкария", 0.5), "08": ("Калмыкия", 0.2),
    "09": ("Карачаево-Черкесия", 0.3), "10": ("Карелия", 0.5), "11": ("Коми", 0.6),
    "12": ("Марий Эл", 0.5), "13": ("Мордовия", 0.5), "14": ("Якутия", 0.6),
    "15": ("Северная Осетия", 0.5), "16": ("Татарстан", 2.5), "116": ("Татарстан", 1.5),
    "716": ("Татарстан", 0.8), "17": ("Тыва", 0.2), "18": ("Удмуртия", 1.0),
    "19": ("Хакасия", 0.4), "21": ("Чувашия", 0.8), "121": ("Чувашия", 0.3),
    "22": ("Алтайский край", 1.5), "23": ("Краснодарский край", 3.0), "93": ("Краснодарский край", 2.5),
    "123": ("Краснодарский край", 2.0), "193": ("Краснодарский край", 1.0),
    "24": ("Красноярский край", 2.0), "124": ("Красноярский край", 1.0),
    "25": ("Приморский край", 1.5), "125": ("Приморский край", 1.0),
    "26": ("Ставропольский край", 1.8), "126": ("Ставропольский край", 0.8),
    "27": ("Хабаровский край", 1.0), "28": ("Амурская область", 0.6),
    "29": ("Архангельская область", 0.8), "30": ("Астраханская область", 0.7),
    "31": ("Белгородская область", 1.0), "32": ("Брянская область", 0.8),
    "33": ("Владимирская область", 1.0), "34": ("Волгоградская область", 1.6),
    "134": ("Волгоградская область", 0.6), "35": ("Вологодская область", 0.8),
    "36": ("Воронежская область", 1.6), "136": ("Воронежская область", 0.6),
    "37": ("Ивановская область", 0.7), "38": ("Иркутская область", 1.6),
    "138": ("Иркутская область", 0.6), "39": ("Калининградская область", 0.8),
    "40": ("Калужская область", 0.8), "41": ("Камчатский край", 0.3),
    "42": ("Кемеровская область", 1.6), "142": ("Кемеровская область", 0.6),
    "43": ("Кировская область", 0.9), "44": ("Костромская область", 0.5),
    "45": ("Курганская область", 0.6), "46": ("Курская область", 0.8),
    "47": ("Ленинградская область", 1.4), "147": ("Ленинградская область", 0.5),
    "48": ("Липецкая область", 0.8), "49": ("Магаданская область", 0.2),
    "50": ("Московская область", 3.0), "90": ("Московская область", 2.0),
    "150": ("Московская область", 2.5), "190": ("Московская область", 2.0),
    "750": ("Московская область", 1.5), "790": ("Московская область", 1.0),
    "51": ("Мурманская область", 0.6), "52": ("Нижегородская область", 2.0),
    "152": ("Нижегородская область", 1.0), "53": ("Новгородская область", 0.5),
    "54": ("Новосибирская область", 1.8), "154": ("Новосибирская область", 0.8),
    "55": ("Омская область", 1.3), "56": ("Оренбургская область", 1.2),
    "156": ("Оренбургская область", 0.3), "57": ("Орловская область", 0.6),
    "58": ("Пензенская область", 0.9), "59": ("Пермский край", 1.6),
    "159": ("Пермский край", 0.8), "60": ("Псковская область", 0.5),
    "61": ("Ростовская область", 2.2), "161": ("Ростовская область", 1.5),
    "761": ("Ростовская область", 0.5), "62": ("Рязанская область", 0.8),
    "63": ("Самарская область", 2.0), "163": ("Самарская область", 1.0),
    "763": ("Самарская область", 0.5), "64": ("Саратовская область", 1.4),
    "164": ("Саратовская область", 0.5), "65": ("Сахалинская область", 0.4),
    "66": ("Свердловская область", 2.4), "96": ("Свердловская область", 1.5),
    "196": ("Свердловская область", 1.2), "67": ("Смоленская область", 0.7),
    "68": ("Тамбовская область", 0.7), "69": ("Тверская область", 0.9),
    "70": ("Томская область", 0.7), "71": ("Тульская область", 1.0),
    "72": ("Тюменская область", 1.3), "172": ("Тюменская область", 0.5),
    "73": ("Ульяновская область", 0.8), "173": ("Ульяновская область", 0.3),
    "74": ("Челябинская область", 2.0), "174": ("Челябинская область", 1.2),
    "75": ("Забайкальский край", 0.6), "76": ("Ярославская область", 0.9),
    "77": ("Москва", 3.0), "97": ("Москва", 2.0), "99": ("Москва", 2.0),
    "177": ("Москва", 2.5), "197": ("Москва", 2.0), "199": ("Москва", 2.0),
    "777": ("Москва", 2.0), "797": ("Москва", 1.5), "799": ("Москва", 1.5),
    "977": ("Москва", 0.6),
    "78": ("Санкт-Петербург", 2.0), "98": ("Санкт-Петербург", 1.5),
    "178": ("Санкт-Петербург", 1.5), "198": ("Санкт-Петербург", 1.2),
    "79": ("Еврейская АО", 0.1), "82": ("Крым", 0.8), "92": ("Севастополь", 0.3),
    "83": ("Ненецкий АО", 0.1), "86": ("ХМАО — Югра", 1.4), "186": ("ХМАО — Югра", 0.6),
    "87": ("Чукотка", 0.05), "89": ("ЯНАО", 0.6), "94": ("Байконур", 0.05),
    "95": ("Чечня", 1.0),
}

UA_LETTERS = "ABCEHIKMOPTX"
UA_REGIONS = {
    "AA": "Київ", "KA": "Київ", "AI": "Київська обл.", "KI": "Київська обл.",
    "BC": "Львів", "HC": "Львів", "AX": "Харків", "KX": "Харків", "AE": "Дніпро",
    "KE": "Дніпро", "BH": "Одеса", "HH": "Одеса", "AH": "Донецьк", "KH": "Донецьк",
    "AB": "Вінниця", "AC": "Волинь", "AK": "Крим", "AM": "Житомир", "AO": "Закарпаття",
    "AP": "Запоріжжя", "AT": "Івано-Франківськ", "BA": "Кропивницький", "BB": "Луганськ",
    "BE": "Миколаїв", "BI": "Полтава", "BK": "Рівне", "BM": "Суми", "BO": "Тернопіль",
    "BT": "Херсон", "BX": "Хмельницький", "CA": "Черкаси", "CB": "Чернігів", "CE": "Чернівці",
}
KZ_REGIONS = {
    "01": "Астана", "02": "Алматы", "03": "Акмолинская", "04": "Актюбинская", "05": "Алматинская",
    "06": "Атырауская", "07": "ЗКО", "08": "Жамбылская", "09": "Карагандинская", "10": "Костанайская",
    "11": "Кызылординская", "12": "Мангистауская", "13": "Туркестанская", "14": "Павлодарская",
    "15": "СКО", "16": "ВКО", "17": "Шымкент", "18": "Абай", "19": "Жетысу", "20": "Улытау",
}
UZ_REGIONS = {"01": "Ташкент", "10": "Ташкентская обл.", "20": "Сырдарья", "25": "Джизак",
              "30": "Самарканд", "40": "Фергана", "50": "Наманган", "60": "Андижан",
              "70": "Кашкадарья", "75": "Сурхандарья", "80": "Бухара", "85": "Навои",
              "90": "Хорезм", "95": "Каракалпакстан"}
DE_CITIES = {"B": "Берлин", "M": "Мюнхен", "HH": "Гамбург", "K": "Кёльн", "F": "Франкфурт",
             "S": "Штутгарт", "D": "Дюссельдорф", "L": "Лейпциг", "H": "Ганновер", "N": "Нюрнберг",
             "HB": "Бремен", "DD": "Дрезден", "E": "Эссен", "DO": "Дортмунд", "MA": "Мангейм",
             "BN": "Бонн", "WOB": "Вольфсбург", "IN": "Ингольштадт", "HD": "Хайдельберг"}
US_STATES = {"CA": "California", "NY": "New York", "TX": "Texas", "FL": "Florida", "NV": "Nevada",
             "WA": "Washington", "IL": "Illinois", "NJ": "New Jersey", "AZ": "Arizona", "CO": "Colorado"}
JP_OFFICES = ["品川", "練馬", "横浜", "名古屋", "大阪", "神戸", "京都", "札幌", "福岡", "湘南"]
JP_KANA = "あいうえかきくけこさすせそたちつてとなにぬねのはひふほまみむめもやゆよらりるろ"
CN_PROVINCES = {"京": "Пекин", "沪": "Шанхай", "粤": "Гуандун", "川": "Сычуань", "浙": "Чжэцзян",
                "苏": "Цзянсу", "鲁": "Шаньдун", "渝": "Чунцин", "津": "Тяньцзинь", "鄂": "Хубэй"}
AE_EMIRATES = {"Dubai": "Дубай", "Abu Dhabi": "Абу-Даби", "Sharjah": "Шарджа", "Ajman": "Аджман"}
TR_CITIES = {"34": "Стамбул", "06": "Анкара", "35": "Измир", "07": "Анталья", "16": "Бурса",
             "01": "Адана", "41": "Коджаэли", "42": "Конья", "61": "Трабзон", "31": "Хатай"}
PL_CITIES = {"WA": "Варшава", "KR": "Краков", "GD": "Гданьск", "PO": "Познань", "WR": "Вроцлав",
             "LU": "Люблин", "SK": "Катовице", "EL": "Лодзь", "BI": "Белосток", "SZ": "Щецин"}
AM_REGIONS = {"01": "Ереван", "02": "Арарат", "03": "Армавир", "04": "Гегаркуник", "05": "Котайк",
              "06": "Лори", "07": "Ширак", "08": "Сюник", "09": "Тавуш", "10": "Вайоц Дзор"}
KR_HANGUL = "가나다라마거너더러머버서어저고노도로모보소오조구누두루무부수우주"


@dataclass
class Plate:
    country: str              # ISO-код страны
    text: str                 # Полный текст номера для отображения
    parts: dict = field(default_factory=dict)   # Именованные части: letters, digits, region, ...
    region: str | None = None  # Код региона (если есть)
    region_name: str | None = None
    style: str = "generic"    # Визуальный стиль для фронта и рендера

    def to_dict(self) -> dict:
        return asdict(self)


def _wchoice(rng: random.Random, weighted: dict[str, tuple[str, float]]) -> str:
    keys = list(weighted)
    weights = [weighted[k][1] for k in keys]
    return rng.choices(keys, weights=weights, k=1)[0]


def _digits(rng: random.Random, n: int, allow_zero: bool = True) -> str:
    while True:
        s = "".join(rng.choice("0123456789") for _ in range(n))
        if allow_zero or int(s) != 0:
            return s


# ---------------------------------------------------------------- Россия

def gen_ru(rng: random.Random) -> Plate:
    l1 = rng.choice(RU_LETTERS)
    l2 = rng.choice(RU_LETTERS)
    l3 = rng.choice(RU_LETTERS)
    digits = _digits(rng, 3, allow_zero=False)
    region = _wchoice(rng, RU_REGIONS)
    return Plate(
        country="RU",
        text=f"{l1}{digits}{l2}{l3} {region}",
        parts={"l1": l1, "digits": digits, "l2": l2, "l3": l3, "region": region},
        region=region,
        region_name=RU_REGIONS[region][0],
        style="ru",
    )


def parse_ru(text: str) -> Plate | None:
    """Разбор введённого пользователем российского номера: А777АА 777."""
    t = text.upper().replace(" ", "").replace("-", "")
    latin_to_cyr = str.maketrans("ABEKMHOPCTYX", "АВЕКМНОРСТУХ")
    t = t.translate(latin_to_cyr)
    if len(t) < 8 or len(t) > 9:
        return None
    l1, digits, l2, l3, region = t[0], t[1:4], t[4], t[5], t[6:]
    # частые опечатки: буква О вместо нуля и наоборот
    digits = digits.replace("О", "0")
    l1, l2, l3 = (x.replace("0", "О") for x in (l1, l2, l3))
    if not (l1 in RU_LETTERS and l2 in RU_LETTERS and l3 in RU_LETTERS and digits.isdigit() and region.isdigit()):
        return None
    if int(digits) == 0:
        return None
    name = RU_REGIONS.get(region, ("Регион " + region, 0))[0]
    return Plate("RU", f"{l1}{digits}{l2}{l3} {region}",
                 {"l1": l1, "digits": digits, "l2": l2, "l3": l3, "region": region},
                 region, name, "ru")


# ---------------------------------------------------------------- Остальные страны

def gen_ua(rng: random.Random) -> Plate:
    region = rng.choice(list(UA_REGIONS))
    digits = _digits(rng, 4)
    series = rng.choice(UA_LETTERS) + rng.choice(UA_LETTERS)
    return Plate("UA", f"{region} {digits} {series}",
                 {"region": region, "digits": digits, "series": series},
                 region, UA_REGIONS[region], "ua")


def gen_by(rng: random.Random) -> Plate:
    region = str(rng.randint(1, 7))
    digits = _digits(rng, 4)
    series = rng.choice("ABEIKMHOPCTX") + rng.choice("ABEIKMHOPCTX")
    names = {"1": "Брест", "2": "Витебск", "3": "Гомель", "4": "Гродно", "5": "Минская обл.", "6": "Могилёв", "7": "Минск"}
    return Plate("BY", f"{digits} {series}-{region}",
                 {"digits": digits, "series": series, "region": region},
                 region, names[region], "by")


def gen_kz(rng: random.Random) -> Plate:
    region = rng.choice(list(KZ_REGIONS))
    digits = _digits(rng, 3)
    letters = "".join(rng.choice("ABCDEFHKLMNOPRSTUVXYZ") for _ in range(3))
    return Plate("KZ", f"{digits} {letters} {region}",
                 {"digits": digits, "letters": letters, "region": region},
                 region, KZ_REGIONS[region], "kz")


def gen_uz(rng: random.Random) -> Plate:
    region = rng.choice(list(UZ_REGIONS))
    l1 = rng.choice("ABCDEFHJKLMNPQRSTUVWXYZ")
    digits = _digits(rng, 3)
    tail = rng.choice("ABCDEFHJKLMNPQRSTUVWXYZ") + rng.choice("ABCDEFHJKLMNPQRSTUVWXYZ")
    return Plate("UZ", f"{region} {l1} {digits} {tail}",
                 {"region": region, "l1": l1, "digits": digits, "tail": tail},
                 region, UZ_REGIONS[region], "uz")


def gen_ge(rng: random.Random) -> Plate:
    a = rng.choice("ABCDEFGHJKLMNOPQRSTUVWXYZ") + rng.choice("ABCDEFGHJKLMNOPQRSTUVWXYZ")
    b = rng.choice("ABCDEFGHJKLMNOPQRSTUVWXYZ") + rng.choice("ABCDEFGHJKLMNOPQRSTUVWXYZ")
    digits = _digits(rng, 3)
    return Plate("GE", f"{a}-{digits}-{b}", {"a": a, "digits": digits, "b": b}, None, "Грузия", "ge")


def gen_am(rng: random.Random) -> Plate:
    region = rng.choice(list(AM_REGIONS))
    series = rng.choice("ABCDEFGHJKLMNOPQRSTUVWXYZ") + rng.choice("ABCDEFGHJKLMNOPQRSTUVWXYZ")
    digits = _digits(rng, 3)
    return Plate("AM", f"{region} {series} {digits}", {"region": region, "series": series, "digits": digits},
                 region, AM_REGIONS[region], "am")


def gen_de(rng: random.Random) -> Plate:
    city = rng.choice(list(DE_CITIES))
    letters = "".join(rng.choice("ABCDEFGHJKLMNPRSTUVWXYZ") for _ in range(rng.choice([1, 2, 2])))
    digits = str(rng.randint(1, 9999))
    return Plate("DE", f"{city} {letters} {digits}", {"city": city, "letters": letters, "digits": digits},
                 city, DE_CITIES[city], "eu")


def gen_us(rng: random.Random) -> Plate:
    state = rng.choice(list(US_STATES))
    letters = "".join(rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZ") for _ in range(3))
    if state == "CA":
        text = f"{rng.randint(1, 9)}{letters}{_digits(rng, 3)}"
    else:
        text = f"{letters}-{_digits(rng, 4)}"
    return Plate("US", text, {"state": state, "letters": letters}, state, US_STATES[state], "us")


def gen_gb(rng: random.Random) -> Plate:
    area = rng.choice("ABCDEFGHKLMNOPRSVWY") + rng.choice("ABCDEFGHJKLMNOPRSTUVWXYZ")
    age = rng.choice(["24", "74", "23", "73", "25", "75", "19", "69", "15", "65"])
    tail = "".join(rng.choice("ABCDEFGHJKLMNOPRSTUVWXYZ") for _ in range(3))
    return Plate("GB", f"{area}{age} {tail}", {"area": area, "age": age, "tail": tail}, None, "Великобритания", "gb")


def gen_fr(rng: random.Random) -> Plate:
    a = rng.choice("ABCDEFGHJKLMNPQRSTVWXYZ") + rng.choice("ABCDEFGHJKLMNPQRSTVWXYZ")
    b = rng.choice("ABCDEFGHJKLMNPQRSTVWXYZ") + rng.choice("ABCDEFGHJKLMNPQRSTVWXYZ")
    return Plate("FR", f"{a}-{_digits(rng, 3)}-{b}", {"a": a, "b": b}, None, "Франция", "eu")


def gen_it(rng: random.Random) -> Plate:
    a = rng.choice("ABCDEFGHJKLMNPRSTVWXYZ") + rng.choice("ABCDEFGHJKLMNPRSTVWXYZ")
    b = rng.choice("ABCDEFGHJKLMNPRSTVWXYZ") + rng.choice("ABCDEFGHJKLMNPRSTVWXYZ")
    return Plate("IT", f"{a} {_digits(rng, 3)} {b}", {"a": a, "b": b}, None, "Италия", "eu")


def gen_es(rng: random.Random) -> Plate:
    letters = "".join(rng.choice("BCDFGHJKLMNPRSTVWXYZ") for _ in range(3))
    return Plate("ES", f"{_digits(rng, 4)} {letters}", {"letters": letters}, None, "Испания", "eu")


def gen_pl(rng: random.Random) -> Plate:
    city = rng.choice(list(PL_CITIES))
    tail = f"{_digits(rng, 4)}{rng.choice('ACEFGHJKLMNPRSTUVWXY')}"
    return Plate("PL", f"{city} {tail}", {"city": city, "tail": tail}, city, PL_CITIES[city], "eu")


def gen_tr(rng: random.Random) -> Plate:
    city = rng.choice(list(TR_CITIES))
    letters = "".join(rng.choice("ABCDEFGHJKLMNPRSTUVYZ") for _ in range(rng.choice([2, 3])))
    return Plate("TR", f"{city} {letters} {_digits(rng, 3)}", {"city": city, "letters": letters},
                 city, TR_CITIES[city], "eu")


def gen_jp(rng: random.Random) -> Plate:
    office = rng.choice(JP_OFFICES)
    cls = rng.choice(["300", "330", "500", "530", "301", "550"])
    kana = rng.choice(JP_KANA)
    num = f"{_digits(rng, 2)}-{_digits(rng, 2)}"
    return Plate("JP", f"{office} {cls} {kana} {num}", {"office": office, "cls": cls, "kana": kana, "num": num},
                 None, "Япония", "jp")


def gen_ae(rng: random.Random) -> Plate:
    emirate = rng.choice(list(AE_EMIRATES))
    code = rng.choice("ABCDEFGHJKLMNOPQRSTUVWXYZ")
    num = str(rng.randint(1, 99999))
    return Plate("AE", f"{emirate} {code} {num}", {"emirate": emirate, "code": code, "num": num},
                 None, AE_EMIRATES[emirate], "ae")


def gen_cn(rng: random.Random) -> Plate:
    prov = rng.choice(list(CN_PROVINCES))
    letter = rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZ")
    tail = "".join(rng.choice("0123456789ABCDEFGHJKLMNPQRSTUVWXYZ0123456789") for _ in range(5))
    return Plate("CN", f"{prov}{letter}·{tail}", {"prov": prov, "letter": letter, "tail": tail},
                 None, CN_PROVINCES[prov], "cn")


def gen_kr(rng: random.Random) -> Plate:
    return Plate("KR", f"{_digits(rng, 3)}{rng.choice(KR_HANGUL)} {_digits(rng, 4)}", {}, None, "Корея", "kr")


COUNTRIES: dict[str, dict] = {
    # code: name, generator, currency, probability weight in world feed
    "RU": {"name": "Россия", "gen": gen_ru, "weight": 10},
    "UA": {"name": "Украина", "gen": gen_ua, "weight": 3},
    "BY": {"name": "Беларусь", "gen": gen_by, "weight": 3},
    "KZ": {"name": "Казахстан", "gen": gen_kz, "weight": 3},
    "UZ": {"name": "Узбекистан", "gen": gen_uz, "weight": 2},
    "GE": {"name": "Грузия", "gen": gen_ge, "weight": 2},
    "AM": {"name": "Армения", "gen": gen_am, "weight": 2},
    "DE": {"name": "Германия", "gen": gen_de, "weight": 3},
    "US": {"name": "США", "gen": gen_us, "weight": 3},
    "GB": {"name": "Великобритания", "gen": gen_gb, "weight": 2},
    "FR": {"name": "Франция", "gen": gen_fr, "weight": 2},
    "IT": {"name": "Италия", "gen": gen_it, "weight": 2},
    "ES": {"name": "Испания", "gen": gen_es, "weight": 2},
    "PL": {"name": "Польша", "gen": gen_pl, "weight": 2},
    "TR": {"name": "Турция", "gen": gen_tr, "weight": 2},
    "JP": {"name": "Япония", "gen": gen_jp, "weight": 2},
    "AE": {"name": "ОАЭ", "gen": gen_ae, "weight": 2},
    "CN": {"name": "Китай", "gen": gen_cn, "weight": 2},
    "KR": {"name": "Корея", "gen": gen_kr, "weight": 1},
}


def generate(country: str = "RU", rng: random.Random | None = None) -> Plate:
    rng = rng or random.SystemRandom()
    if country == "WORLD":
        country = pick_country(rng)
    gen: Callable[[random.Random], Plate] = COUNTRIES[country]["gen"]
    return gen(rng)


def pick_country(rng: random.Random, allowed: list[str] | None = None) -> str:
    codes = [c for c in COUNTRIES if not allowed or c in allowed] or list(COUNTRIES)
    weights = [COUNTRIES[c]["weight"] for c in codes]
    return rng.choices(codes, weights=weights, k=1)[0]


def country_list() -> list[dict]:
    return [{"code": c, "name": v["name"]} for c, v in COUNTRIES.items()]
