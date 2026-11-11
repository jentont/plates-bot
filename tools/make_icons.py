"""Генератор кастомных TGS-иконок (Lottie, сжатый gzip) для мини-апы.

Запуск:  python tools/make_icons.py
Результат: webapp/icons/*.tgs (+ *.json для отладки).

Иконки монохромные (белые), на фронте перекрашиваются через CSS `fill: currentColor`.
Формат соответствует требованиям Telegram к TGS: 512x512, 60 fps, до 3 секунд.
"""
from __future__ import annotations

import gzip
import json
import math
import os
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "webapp" / "icons"
FPS = 60
W = 512

EASE_IN_OUT = {"i": {"x": [0.42], "y": [1]}, "o": {"x": [0.58], "y": [0]}}
EASE_OUT = {"i": {"x": [0.2], "y": [1]}, "o": {"x": [0.4], "y": [0]}}
LINEAR = {"i": {"x": [0.999], "y": [0.999]}, "o": {"x": [0.001], "y": [0.001]}}


# ------------------------------------------------------------------ helpers

def static(v):
    return {"a": 0, "k": v}


def anim(keys: list[tuple[int, list | float]], ease=EASE_IN_OUT):
    """keys: [(frame, value), ...] -> animated property."""
    out = []
    for i, (t, v) in enumerate(keys):
        if not isinstance(v, list):
            v = [v]
        kf = {"t": t, "s": v}
        if i < len(keys) - 1:
            kf.update(ease)
        out.append(kf)
    return {"a": 1, "k": out}


def fill(color=(1, 1, 1), opacity=100):
    return {"ty": "fl", "c": static(list(color) + [1]), "o": static(opacity), "r": 1}


def transform(p=(0, 0), s=(100, 100), r=0, o=100, a=(0, 0)):
    return {"ty": "tr", "p": p if isinstance(p, dict) else static(list(p)), "a": static(list(a)),
            "s": s if isinstance(s, dict) else static(list(s)),
            "r": r if isinstance(r, dict) else static(r),
            "o": o if isinstance(o, dict) else static(o), "sk": static(0), "sa": static(0)}


def rect(w, h, r=0, p=(0, 0)):
    return {"ty": "rc", "d": 1, "s": static([w, h]), "p": static(list(p)), "r": static(r)}


def ellipse(w, h, p=(0, 0)):
    return {"ty": "el", "d": 1, "s": static([w, h]), "p": static(list(p))}


def path(points: list[tuple[float, float]], closed=True):
    n = len(points)
    return {"ty": "sh", "d": 1, "ks": static({"c": closed, "v": [list(p) for p in points],
                                              "i": [[0, 0]] * n, "o": [[0, 0]] * n})}


def group(items: list, tr=None, name="g"):
    return {"ty": "gr", "nm": name, "it": items + [tr or transform()]}


def layer(shapes: list, name="layer", ks=None, ip=0, op=180):
    ks = ks or {}
    return {
        "ddd": 0, "ind": 1, "ty": 4, "nm": name, "sr": 1,
        "ks": {"o": ks.get("o", static(100)), "r": ks.get("r", static(0)),
               "p": ks.get("p", static([W / 2, W / 2, 0])), "a": ks.get("a", static([0, 0, 0])),
               "s": ks.get("s", static([100, 100, 100]))},
        "ao": 0, "shapes": shapes, "ip": ip, "op": op, "st": 0, "bm": 0,
    }


def composition(layers: list, name: str, frames=180):
    return {"tgs": 1, "v": "5.5.2", "fr": FPS, "ip": 0, "op": frames, "w": W, "h": W,
            "nm": name, "ddd": 0, "assets": [], "layers": layers}


def stroke(width, color=(1, 1, 1), opacity=100):
    return {"ty": "st", "c": static(list(color) + [1]), "o": static(opacity), "w": static(width), "lc": 2, "lj": 2}


def ring(outer, inner):
    """Кольцо: окружность с обводкой (merge paths в lottie-web не поддерживаются)."""
    w = (outer - inner) / 2
    return [ellipse(outer - w, outer - w), stroke(w)]


def arc(r, a0, a1, n=14):
    """Дуга окружности как ломаная (в градусах), для обводки."""
    pts = []
    for k in range(n + 1):
        a = math.radians(a0 + (a1 - a0) * k / n)
        pts.append((r * math.cos(a), r * math.sin(a)))
    return pts


def save(name: str, comp: dict):
    OUT.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(comp, separators=(",", ":"), ensure_ascii=False).encode()
    (OUT / f"{name}.json").write_bytes(raw)
    with gzip.open(OUT / f"{name}.tgs", "wb", compresslevel=9) as f:
        f.write(raw)
    print(f"{name:10s} {len(raw):6d} B json  {os.path.getsize(OUT / (name + '.tgs')):5d} B tgs")


# ------------------------------------------------------------------ icons

def icon_spin():
    """Номерной знак с тремя барабанами: полосы бегут вниз и гаснут у кромки."""
    frame = group([rect(376, 176, 30), stroke(24)], name="frame")
    reels = []
    for i, x in enumerate((-110, 0, 110)):
        for j in range(3):
            d = i * 8 + j * 20
            reels.append(group([rect(70, 44, 12), fill()],
                               transform(p=anim([(d, [x, -70]), (60 + d, [x, 70])], LINEAR),
                                         o=anim([(d, 0), (15 + d, 100), (45 + d, 100), (60 + d, 0)], LINEAR))))
    return composition([layer([frame] + reels, "spin", op=100)], "spin", frames=100)


def icon_feed():
    """Лента: три строки, индикатор «live» пульсирует."""
    rows = []
    for j, y in enumerate((-120, 0, 120)):
        w = 300 if j != 1 else 240
        rows.append(group([rect(w, 44, 22, (30, y)), fill()]))
    dot = group([ellipse(44, 44), fill()],
                transform(p=static([-190, -120]),
                          s=anim([(0, [100, 100]), (40, [150, 150]), (80, [100, 100])]),
                          o=anim([(0, 100), (40, 55), (80, 100)])))
    halo = group([ellipse(44, 44), fill(opacity=35)],
                 transform(p=static([-190, -120]), s=anim([(0, [100, 100]), (80, [260, 260])], EASE_OUT),
                           o=anim([(0, 60), (80, 0)], EASE_OUT)))
    return composition([layer([halo, dot] + rows, "feed", op=80)], "feed", frames=80)


def icon_garage():
    """Гараж: ворота поднимаются (верхние планки гаснут, уходя под крышу)."""
    roof = group([path([(-220, 0), (0, -170), (220, 0), (220, 40), (-220, 40)]), fill()])
    walls = group([rect(400, 40, 0, (0, 40)), rect(70, 190, 0, (-165, 115)), rect(70, 190, 0, (165, 115)), fill()])
    slats = []
    for j in range(4):
        y = 75 + j * 36
        slats.append(group([rect(236, 28, 8), fill()],
                           transform(p=anim([(0, [0, y]), (60, [0, y - 70]), (110, [0, y - 70]), (170, [0, y])]),
                                     o=anim([(0, 100), (60, 0 if j == 0 else 100), (110, 0 if j == 0 else 100), (170, 100)]))))
    return composition([layer([roof, walls] + slats, "garage", op=180)], "garage", frames=180)


def icon_world():
    """Глобус: кольцо и бегущие меридианы."""
    outer = group(ring(400, 352))
    eq = group([rect(352, 36, 18), fill()])
    meridians = []
    for j, ph in enumerate((0, 1, 2)):
        # меридиан = эллипс, ширина которого меняется от 0 до 300 (имитирует вращение)
        wk = []
        for f in range(0, 181, 15):
            t = (f / 180) * 2 * math.pi + ph * 2 * math.pi / 3
            wk.append((f, [max(abs(math.cos(t)) * 300, 8), 352]))
        meridians.append(group([ellipse(280, 330), stroke(20, opacity=85)],
                               transform(s=anim([(f, [v[0] / 300 * 100, 100]) for f, v in wk], LINEAR))))
    return composition([layer([outer, eq] + meridians, "world", op=180)], "world", frames=180)


def icon_bolt():
    """Энергия: молния пульсирует."""
    bolt = path([(40, -230), (-120, 30), (-10, 30), (-60, 230), (130, -40), (10, -40)])
    g = group([bolt, fill()], transform(s=anim([(0, [100, 100]), (30, [112, 112]), (60, [100, 100])]),
                                        r=anim([(0, 0), (30, -4), (60, 0)])))
    glow = group([bolt, fill(opacity=40)], transform(s=anim([(0, [100, 100]), (60, [150, 150])], EASE_OUT),
                                                     o=anim([(0, 50), (60, 0)], EASE_OUT)))
    return composition([layer([glow, g], "bolt", op=60)], "bolt", frames=60)


def icon_star():
    pts = []
    for k in range(10):
        r = 230 if k % 2 == 0 else 100
        a = -math.pi / 2 + k * math.pi / 5
        pts.append((r * math.cos(a), r * math.sin(a)))
    star = group([path(pts), fill()], transform(s=anim([(0, [0, 0]), (40, [115, 115]), (60, [100, 100])], EASE_OUT),
                                                r=anim([(0, -40), (60, 0)], EASE_OUT)))
    sparks = []
    for k in range(6):
        a = k * math.pi / 3
        x, y = 150 * math.cos(a), 150 * math.sin(a)
        sparks.append(group([ellipse(26, 26), fill()],
                            transform(p=anim([(20, [x, y]), (70, [x * 1.9, y * 1.9])], EASE_OUT),
                                      s=anim([(20, [100, 100]), (70, [0, 0])], EASE_OUT))))
    return composition([layer(sparks + [star], "star", op=90)], "star", frames=90)


def icon_coin():
    """Монета переворачивается (масштаб по X)."""
    coin = group(ring(380, 300))
    sym = group([rect(120, 36, 18, (0, -40)), rect(36, 220, 18, (-40, 20)), rect(140, 36, 18, (-4, 50)),
                 rect(36, 90, 18, (40, -10)), fill()])
    g = group([coin, sym], transform(s=anim([(0, [100, 100]), (45, [8, 100]), (90, [100, 100])], EASE_IN_OUT)))
    return composition([layer([g], "coin", op=90)], "coin", frames=90)


def icon_sliders():
    rows = []
    for j, (y, kx) in enumerate(((-120, -90), (0, 70), (120, -20))):
        rows.append(group([rect(360, 24, 12, (0, y)), fill(opacity=60)]))
        knob = group([ellipse(72, 72), fill()],
                     transform(p=anim([(0, [kx, y]), (50, [-kx * 0.8, y]), (100, [kx, y])])))
        rows.append(knob)
    return composition([layer(rows, "sliders", op=100)], "sliders", frames=100)


def icon_share():
    arrow = group([path([(0, -190), (170, -20), (80, -20), (80, 100), (-80, 100), (-80, -20), (-170, -20)]), fill()],
                  transform(p=anim([(0, [0, 10]), (40, [0, -30]), (80, [0, 10])])))
    tray = group([rect(380, 40, 20, (0, 190)), rect(40, 150, 20, (-170, 135)), rect(40, 150, 20, (170, 135)), fill()])
    return composition([layer([arrow, tray], "share", op=80)], "share", frames=80)


def icon_trophy():
    cup = group([path([(-150, -200), (150, -200), (120, 20), (0, 90), (-120, 20)]), fill()])
    handles = group([path(arc(70, 90, 270), closed=False), stroke(26)], transform(p=static([-170, -120])))
    handles2 = group([path(arc(70, -90, 90), closed=False), stroke(26)], transform(p=static([170, -120])))
    stem = group([rect(60, 80, 10, (0, 130)), rect(220, 44, 16, (0, 190)), fill()])
    shine = group([rect(30, 120, 15, (-60, -100)), fill(opacity=60)],
                  transform(p=anim([(0, [-200, 0]), (60, [200, 0])], EASE_IN_OUT), r=static(20)))
    lay = layer([cup, handles, handles2, stem, shine], "trophy", op=120)
    return composition([lay], "trophy", frames=120)


def icon_lock():
    body = group([rect(300, 220, 40, (0, 100)), fill()])
    key = group([ellipse(60, 60, (0, 70)), rect(24, 70, 12, (0, 110)), fill((0.07, 0.08, 0.12))])
    shackle = group([path(arc(92, 180, 360) + [(92, 10), (92, 10)], closed=False), stroke(34)],
                    transform(p=anim([(0, [0, -90]), (40, [0, -130]), (90, [0, -130]), (120, [0, -90])])))
    return composition([layer([shackle, body, key], "lock", op=120)], "lock", frames=120)


def icon_check():
    mark = group([path([(-170, 10), (-110, -50), (-40, 30), (120, -140), (180, -80), (-40, 150)]), fill()],
                 transform(s=anim([(0, [0, 0]), (30, [115, 115]), (45, [100, 100])], EASE_OUT)))
    return composition([layer([mark], "check", op=60)], "check", frames=60)


def icon_search():
    glass = group(ring(260, 200), transform(p=static([-40, -40])))
    handle = group([rect(60, 170, 30, (0, 0)), fill()], transform(p=static([120, 120]), r=static(-45)))
    g = group([glass, handle], transform(p=anim([(0, [0, 0]), (30, [-20, 20]), (60, [20, -10]), (90, [0, 0])])))
    return composition([layer([g], "search", op=90)], "search", frames=90)


ICONS = {
    "spin": icon_spin, "feed": icon_feed, "garage": icon_garage, "world": icon_world,
    "bolt": icon_bolt, "star": icon_star, "coin": icon_coin, "sliders": icon_sliders,
    "share": icon_share, "trophy": icon_trophy, "lock": icon_lock, "check": icon_check,
    "search": icon_search,
}

if __name__ == "__main__":
    for name, fn in ICONS.items():
        save(name, fn())
