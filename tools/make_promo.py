"""Анимация прокрутки номера для рассылки: GIF и MP4.

Запуск из корня проекта:  python tools/make_promo.py
Результат: assets/brand/spin.gif (960x540) и assets/brand/spin.mp4 (1280x720).

Сюжет ~4.5 с: рамка падает на дорогу, барабаны крутят символы, они встают по одному
на А777АА 777, рамка загорается «Мифический», вспышка искр, цена набегает до 60 000 000 ₽.
Конец кадра повторяет начало, поэтому в цикле анимация не дёргается.
"""
from __future__ import annotations

import math
import random
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.plates import Plate  # noqa: E402
from platesbot.render import _holder, _logo, _mix, _spark, _tw, font  # noqa: E402

OUT = ROOT / "assets" / "brand"
W, H, FPS = 1280, 720, 30
RED = (255, 59, 59)
GREY = (139, 143, 152)
LAT = "ABEKMHOPCTYX"
FINAL = {"l1": "А", "digits": "777", "l2": "А", "l3": "А", "region": "777"}
SLOTS = ["l1", "d0", "d1", "d2", "l2", "l3", "r0", "r1", "r2"]

T_DROP, T_SPIN, T_STEP = 0.55, 1.35, 0.13           # падение, крутка до первой остановки, шаг остановки
T_END = T_SPIN + T_STEP * len(SLOTS)                 # все символы встали
DURATION = 4.6


def ease_out(t: float) -> float:
    return 1 - (1 - t) ** 3


def background() -> Image.Image:
    """Ночная дорога без зерна: гладкие градиенты хорошо жмутся в GIF."""
    img = Image.new("RGB", (W, H), (6, 6, 7))
    r = Image.radial_gradient("L").resize((int(W * 1.1), int(W * 1.1)))
    mask = Image.new("L", (W, H), 255)
    mask.paste(r, (int(W * .5 - W * .55), int(H * .42 - W * .55)))
    img = Image.composite(img, Image.new("RGB", (W, H), (40, 41, 47)), mask)
    road = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(road)
    top, cx = int(H * .5), W // 2
    for side in (-1, 1):
        d.line([(cx + side * 160, top), (cx + side * 980, H)], fill=30, width=3)
    img.paste((255, 255, 255), (0, 0), road.filter(ImageFilter.GaussianBlur(1.2)))
    d = ImageDraw.Draw(img)
    _logo(d, 48, 40)
    tiers = ["#8E97A8", "#5FB2FF", "#7C6CFF", "#E85CFF", "#FFB020", "#FF3B3B"]
    bw, gap = 46, 7
    x0 = W - 48 - (bw * 6 + gap * 5)
    for i, c in enumerate(tiers):
        d.rounded_rectangle([x0 + i * (bw + gap), 58, x0 + i * (bw + gap) + bw, 65], radius=4, fill=c)
    return img


def road_marks(img: Image.Image, phase: float) -> None:
    """Осевая разметка бежит на зрителя; phase 0..1 — сдвиг на один штрих."""
    layer = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(layer)
    top, cx, n = int(H * .5), W // 2, 7
    for k in range(-1, n):
        t0, t1 = ((k + phase) / n), ((k + phase + .55) / n)
        if t1 <= 0:
            continue
        t0, t1 = max(t0, 0) ** 1.8, min(t1, 1) ** 1.8
        y0, y1 = top + (H - top) * t0, top + (H - top) * t1
        w0, w1 = 2 + 16 * t0, 2 + 16 * t1
        d.polygon([(cx - w0, y0), (cx + w0, y0), (cx + w1, y1), (cx - w1, y1)], fill=int(22 + 60 * t1))
    img.paste((255, 255, 255), (0, 0), layer.filter(ImageFilter.GaussianBlur(1.2)))


def plate_at(t: float, rng: random.Random) -> Plate:
    """Номер в момент t: остановившиеся слоты — финальные, остальные — случайные."""
    final = [FINAL["l1"], *FINAL["digits"], FINAL["l2"], FINAL["l3"], *FINAL["region"]]
    chars = []
    for i, name in enumerate(SLOTS):
        stop = T_SPIN + T_STEP * i
        if t >= stop:
            chars.append(final[i])
        elif name.startswith(("d", "r")):
            chars.append(rng.choice("0123456789"))
        else:
            chars.append(rng.choice("АВЕКМНОРСТУХ"))
    parts = {"l1": chars[0], "digits": "".join(chars[1:4]), "l2": chars[4], "l3": chars[5], "region": "".join(chars[6:9])}
    return Plate(country="RU", text="", parts=parts, style="ru")


def frame(bg: Image.Image, t: float, rng: random.Random, sparks: list) -> Image.Image:
    img = bg.copy()
    spinning = t < T_END
    road_marks(img, (t * (3.2 if spinning else 0.9)) % 1)

    done = t >= T_END
    lip, color = ("Мифический", RED) if done else ("· · ·", GREY)
    hold = _holder(plate_at(t, rng), 820, lip, color)

    # падение сверху с отскоком, потом лёгкое дыхание
    if t < T_DROP:
        k = ease_out(t / T_DROP)
        dy = -380 * (1 - k) + 26 * math.sin(k * math.pi) * (1 - k)
    else:
        dy = 4 * math.sin((t - T_DROP) * 2.2)
    shake = 0.0
    if done and t < T_END + 0.35:                     # удар при остановке
        s = (t - T_END) / 0.35
        shake = 9 * (1 - s) * math.sin(s * 40)
    scale = 1.0 + (0.06 * (1 - (t - T_END) / 0.3) if done and t < T_END + 0.3 else 0)
    if scale != 1.0:
        hold = hold.resize((int(hold.width * scale), int(hold.height * scale)), Image.LANCZOS)
    hx = (W - hold.width) // 2 + int(shake)
    hy = int(H * .23) + int(dy) - (hold.height - _holder_h()) // 2

    # тень и красный отблеск на асфальте
    shadow = Image.new("L", (W, H), 0)
    ImageDraw.Draw(shadow).ellipse([hx + 30, hy + hold.height - 4, hx + hold.width - 30, hy + hold.height + 40],
                                   fill=int(220 * min(1, max(0.2, 1 + dy / 380))))
    img.paste((0, 0, 0), (0, 0), shadow.filter(ImageFilter.GaussianBlur(18)))
    if done:
        a = min(1, (t - T_END) / 0.4)
        glow = Image.new("L", (W, H), 0)
        ImageDraw.Draw(glow).ellipse([W * .28, H * .6, W * .72, H * .74], fill=int(130 * a))
        img.paste(RED, (0, 0), glow.filter(ImageFilter.GaussianBlur(50)))

    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    refl = hold.transpose(Image.FLIP_TOP_BOTTOM).crop((0, 0, hold.width, int(hold.height * .45)))
    fade = Image.linear_gradient("L").resize(refl.size).point(lambda v: int((255 - v) * .16))
    refl.putalpha(ImageChops.multiply(refl.getchannel("A"), fade))
    layer.alpha_composite(refl, (hx, hy + hold.height + 8))
    layer.alpha_composite(hold, (hx, hy))
    img.paste(layer, (0, 0), layer)

    d = ImageDraw.Draw(img)
    # искры: вылетают при остановке
    if done and not sparks:
        r2 = random.Random(7)
        for _ in range(70):
            ang = r2.uniform(0, math.tau)
            sp = r2.uniform(260, 900)
            sparks.append((W / 2 + math.cos(ang) * 300, H * .36 + math.sin(ang) * 40, math.cos(ang) * sp,
                           math.sin(ang) * sp * .6 - 260, r2.uniform(4, 13), r2.random()))
    for (x0, y0, vx, vy, size, mix) in sparks:
        dt = t - T_END
        if dt > 1.1:
            break
        x, y = x0 + vx * dt, y0 + vy * dt + 520 * dt * dt
        life = 1 - dt / 1.1
        _spark(d, x, y, size * life, _mix(RED, (255, 255, 255), mix))

    # подпись и цена
    f_title = font("display", 46)
    title = "Крути номера"
    d.text(((W - _tw(d, title, f_title)) // 2, int(H * .74)), title, font=f_title, fill=(242, 243, 245))
    f_sub = font("text", 27)
    if done:
        k = ease_out(min(1, (t - T_END) / 0.8))
        price = f"{int(60_000_000 * k / 10000) * 10000:,} ₽".replace(",", " ")
        sub, col = f"Мифический · {price}", RED
    else:
        sub, col = "Редкость и цена каждого номера", (150, 154, 163)
    d.text(((W - _tw(d, sub, f_sub)) // 2, int(H * .74) + 66), sub, font=f_sub, fill=col)
    return img


_HH: list[int] = []


def _holder_h() -> int:
    if not _HH:
        _HH.append(_holder(plate_at(99, random.Random(0)), 820, "x", GREY).height)
    return _HH[0]


def main() -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        try:
            import imageio_ffmpeg
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        except ImportError:
            sys.exit("Нужен ffmpeg: поставь его или pip install imageio-ffmpeg")
    OUT.mkdir(parents=True, exist_ok=True)
    bg = background()
    sparks: list = []
    with tempfile.TemporaryDirectory() as tmp:
        n = int(DURATION * FPS)
        for i in range(n):
            # барабаны меняют символы ~15 раз в секунду, а не каждый кадр: читается лучше
            frame(bg, i / FPS, random.Random(i // 2), sparks).save(Path(tmp) / f"f{i:04d}.png")
        src = str(Path(tmp) / "f%04d.png")
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", src,
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-movflags", "+faststart",
                        str(OUT / "spin.mp4")], check=True)
        pal = str(Path(tmp) / "pal.png")
        vf = "fps=20,scale=960:-1:flags=lanczos"
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", src,
                        "-vf", vf + ",palettegen=max_colors=128:stats_mode=diff", pal], check=True)
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", src, "-i", pal,
                        "-lavfi", vf + "[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle",
                        "-loop", "0", str(OUT / "spin.gif")], check=True)
        (OUT / "spin_last.png").write_bytes((Path(tmp) / f"f{n - 1:04d}.png").read_bytes())
        (OUT / "spin_mid.png").write_bytes((Path(tmp) / f"f{int(T_SPIN * FPS + 4):04d}.png").read_bytes())
    for name in ("spin.gif", "spin.mp4"):
        print(name, round((OUT / name).stat().st_size / 1e6, 2), "МБ")


if __name__ == "__main__":
    main()
