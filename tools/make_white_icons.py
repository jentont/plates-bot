"""Перекрашивает 3D-иконки мини-апы в единый белый: цвет убирается, объём (светотень) остаётся.

Запуск: python tools/make_white_icons.py
Исходники цветных иконок лежат в истории git; скрипт берёт файлы из webapp/img/3d и
перезаписывает их, поэтому повторный запуск безопасен (белое остаётся белым).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

DIR = Path(__file__).resolve().parent.parent / "webapp" / "img" / "3d"
DARK, LIGHT = 118, 255        # самая глубокая тень и самый яркий блик


def whiten(path: Path) -> None:
    img = np.asarray(Image.open(path).convert("RGBA")).astype(np.float32)
    rgb, alpha = img[..., :3], img[..., 3]
    lum = rgb @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    seen = alpha > 40
    if not seen.any():
        return
    lo, hi = np.percentile(lum[seen], [3, 99.5])
    k = np.clip((lum - lo) / max(hi - lo, 1), 0, 1) ** 0.75
    v = DARK + (LIGHT - DARK) * k
    out = np.dstack([v, v, v * 1.0, alpha]).clip(0, 255).astype(np.uint8)
    Image.fromarray(out, "RGBA").save(path, optimize=True)


def main() -> None:
    for p in sorted(DIR.glob("*.png")):
        whiten(p)
        print("белая:", p.name)


if __name__ == "__main__":
    main()
