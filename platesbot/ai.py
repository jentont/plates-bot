"""Оценка номера нейросетью (Claude). Включается, если задан ANTHROPIC_API_KEY.

Эвристика в core/rarity.py работает всегда; нейросеть даёт «второе мнение»:
рыночную цену и короткий комментарий, как на площадках продажи номеров.
Ответы кэшируются в SQLite по тексту номера.
"""
from __future__ import annotations

import json
import logging

from core.plates import Plate
from core.rarity import Evaluation

log = logging.getLogger("ai")

SYSTEM = (
    "Ты эксперт по рынку «красивых» автомобильных номеров в России и мире. "
    "Тебе дают номер, страну и эвристическую оценку. Назови реалистичную рыночную цену номера "
    "на вторичном рынке (в рублях для России, в долларах для остальных стран) и объясни одной-двумя "
    "фразами, за что ценится или почему он обычный. Пиши по-русски, без эмодзи, коротко. "
    "Обычный номер без признаков оценивай в 0."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "price": {"type": "integer", "description": "Цена в рублях (Россия) или долларах (другие страны), 0 если номер обычный"},
        "comment": {"type": "string", "description": "Короткий комментарий, 1-2 предложения"},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
    },
    "required": ["price", "comment", "confidence"],
    "additionalProperties": False,
}


class AIValuer:
    def __init__(self, api_key: str, model: str, storage):
        from anthropic import AsyncAnthropic
        self.client = AsyncAnthropic(api_key=api_key)
        self.model = model
        self.storage = storage

    async def value(self, plate: Plate, ev: Evaluation, country_name: str) -> dict:
        cached = self.storage.ai_get(plate.text)
        if cached:
            return cached
        prompt = (
            f"Номер: {plate.text}\nСтрана: {country_name}" + (f", регион: {plate.region_name}" if plate.region_name else "") +
            f"\nЭвристика: {ev.score} очков, уровень «{ev.tier_name}», признаки: "
            + "; ".join(r["title"] for r in ev.reasons) + "."
        )
        response = await self.client.beta.messages.create(
            model=self.model,
            max_tokens=1024,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=SYSTEM,
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[{"role": "user", "content": prompt}],
        )
        if response.stop_reason == "refusal":
            data = {"price": 0, "comment": "Нейросеть не стала оценивать этот номер.", "confidence": "low"}
        else:
            text = next(b.text for b in response.content if b.type == "text")
            data = json.loads(text)
        self.storage.ai_put(plate.text, data)
        return data
