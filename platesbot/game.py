"""Игровая логика, общая для мини-апы, чата, inline-режима и виджета."""
from __future__ import annotations

import random

from core.plates import COUNTRIES, Plate, generate, pick_country, parse_ru
from core.rarity import Evaluation, evaluate

from .config import Config
from .storage import Storage


class NoEnergy(Exception):
    pass


class Game:
    def __init__(self, storage: Storage, config: Config):
        self.storage = storage
        self.config = config
        self.rng = random.SystemRandom()

    def country_for(self, user_id: int, override: str | None = None) -> str:
        if override and override in COUNTRIES:
            return override
        if override == "WORLD":
            return pick_country(self.rng)
        s = self.storage.settings(user_id)
        if s["mode"] == "world":
            return pick_country(self.rng)
        if s["mode"] == "custom" and s["countries"]:
            return pick_country(self.rng, [c for c in s["countries"] if c in COUNTRIES])
        return "RU"

    def spin(self, tg_user: dict, source: str, country: str | None = None) -> dict:
        """Списывает энергию и создаёт прокрутку. Бросает NoEnergy."""
        self.storage.touch_user(tg_user)
        if not self.storage.consume_energy(tg_user["id"]):
            raise NoEnergy()
        code = self.country_for(tg_user["id"], country)
        plate = generate(code, self.rng)
        ev = evaluate(plate)
        return self.storage.add_roll(tg_user["id"], plate, ev, source)

    def roll_objects(self, roll: dict) -> tuple[Plate, Evaluation]:
        return Plate(**roll["plate"]), Evaluation(**roll["eval"])

    @staticmethod
    def country_name(code: str) -> str:
        return COUNTRIES.get(code, {"name": code})["name"]

    @staticmethod
    def estimate(text: str) -> tuple[Plate, Evaluation] | None:
        plate = parse_ru(text)
        if not plate:
            return None
        return plate, evaluate(plate)

    def random_world(self) -> tuple[Plate, Evaluation]:
        plate = generate(pick_country(self.rng), self.rng)
        return plate, evaluate(plate)
