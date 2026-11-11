"""Пересчитать core/distribution.json — распределение очков по странам для «топ X%».

Запускать после любой правки правил оценки в core/rarity.py:  python tools/make_distribution.py
"""
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.plates import COUNTRIES  # noqa: E402
from core.rarity import DIST_FILE, build_distribution  # noqa: E402

data = {}
for country in COUNTRIES:
    counts = Counter(build_distribution(country))
    data[country] = sorted([score, n] for score, n in counts.items())
DIST_FILE.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
print(DIST_FILE, DIST_FILE.stat().st_size, "байт")
