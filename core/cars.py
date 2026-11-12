"""Каталог машин: от развалюх до гиперкаров.

Машина покупается за деньги с продажи номеров и появляется на карточке игрока:
вид спереди, номер стоит на бампере. Один и тот же набор параметров рисуют
Pillow (platesbot/render.py) и SVG в мини-апе (webapp/app.js), поэтому машина
выглядит одинаково везде.

Параметры формы (в долях ширины машины):
  bh — высота кузова, ch — высота кабины, cw — ширина кабины снизу,
  lights — фары: round | rect | slim, grille — решётка: bars | kidney | horseshoe | wide | slats | none.
"""
from __future__ import annotations

CARS: list[dict] = [
    {"id": "zhiguli", "name": "ВАЗ-2107 «Жигули»", "price": 60_000, "color": "#C9B58B",
     "bh": .26, "ch": .14, "cw": .66, "lights": "rect", "grille": "bars", "chrome": True},
    {"id": "granta", "name": "Lada Granta", "price": 700_000, "color": "#8C96A3",
     "bh": .25, "ch": .13, "cw": .62, "lights": "rect", "grille": "slats"},
    {"id": "camry", "name": "Toyota Camry", "price": 3_500_000, "color": "#1E1F24",
     "bh": .24, "ch": .12, "cw": .60, "lights": "slim", "grille": "wide"},
    {"id": "bmw", "name": "BMW M5", "price": 12_000_000, "color": "#1F4FB5",
     "bh": .24, "ch": .11, "cw": .58, "lights": "slim", "grille": "kidney"},
    {"id": "gelik", "name": "Mercedes G 63", "price": 25_000_000, "color": "#0E0F11",
     "bh": .27, "ch": .17, "cw": .70, "lights": "round", "grille": "slats", "chrome": True},
    {"id": "porsche", "name": "Porsche 911 Turbo S", "price": 32_000_000, "color": "#D9D9D4",
     "bh": .23, "ch": .09, "cw": .52, "lights": "round", "grille": "none"},
    {"id": "lambo", "name": "Lamborghini Huracán", "price": 45_000_000, "color": "#E8C400",
     "bh": .22, "ch": .07, "cw": .50, "lights": "slim", "grille": "wide"},
    {"id": "rolls", "name": "Rolls-Royce Phantom", "price": 80_000_000, "color": "#3B1F5E",
     "bh": .27, "ch": .13, "cw": .64, "lights": "rect", "grille": "bars", "chrome": True},
    {"id": "bugatti", "name": "Bugatti Chiron", "price": 350_000_000, "color": "#0B3E91",
     "bh": .23, "ch": .07, "cw": .50, "lights": "slim", "grille": "horseshoe"},
]
BY_ID = {c["id"]: c for c in CARS}

USD_RATE = 90
SCRAP = 1000          # обычный номер уходит «на металл» за эту сумму


def plate_money(roll: dict) -> int:
    """Сколько рублей дадут за номер при продаже за деньги."""
    ev, country = roll["eval"], roll["plate"]["country"]
    value = ev["price_rub"] if country == "RU" else ev["price_usd"] * USD_RATE
    return max(int(value), SCRAP)


def fmt_money(n: int) -> str:
    return f"{int(n):,} ₽".replace(",", " ")
