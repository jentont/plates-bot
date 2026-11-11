"""Аватарка и баннер бота в стиле мини-апы.

Запуск из корня проекта:  python tools/make_brand.py
Результат: assets/brand/avatar_2048.png, avatar_1024.png, avatar_640.png,
           banner_1280.png, banner_640.png (картинка описания бота, 640x360).
"""
from __future__ import annotations

import math
import random
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from platesbot.render import _holder, _logo, _mix, _spark, _tw, font  # noqa: E402
from core.plates import parse_ru  # noqa: E402

OUT = ROOT / "assets" / "brand"
RED = (255, 59, 59)
SILVER = (201, 204, 210)
TITLE_FONT = str(ROOT / "assets" / "fonts" / "Oswald.ttf")   # узкий жирный гротеск с кириллицей
HERO = parse_ru("А777АА 777")


# ------------------------------------------------------------ общие слои

def studio(w: int, h: int, spot=(0.5, 0.45), spot_r=0.62, base=(6, 6, 7), light=(44, 45, 51)) -> Image.Image:
    """Тёмная студия: пятно света, луч сверху, мягкая виньетка, зерно."""
    img = Image.new("RGB", (w, h), base)
    r = Image.radial_gradient("L").resize((int(w * spot_r * 2), int(w * spot_r * 2)))
    mask = Image.new("L", (w, h), 255)
    mask.paste(r, (int(w * spot[0] - w * spot_r), int(h * spot[1] - w * spot_r)))
    img = Image.composite(img, Image.new("RGB", (w, h), light), mask)
    beam = Image.new("L", (w, h), 0)
    ImageDraw.Draw(beam).polygon([(w * .42, 0), (w * .58, 0), (w * .66, h), (w * .34, h)], fill=26)
    img.paste((255, 255, 255), (0, 0), beam.filter(ImageFilter.GaussianBlur(w * .05)))
    noise = Image.effect_noise((w, h), 26).convert("RGB")
    return Image.blend(img, ImageChops.multiply(img, noise), .45)


def plate_holder(width: int, lip: str = "Мифический") -> Image.Image:
    return _holder(HERO, width, lip, RED)


def drop_shadow(alpha: Image.Image, size, offset, blur, strength=210) -> Image.Image:
    sh = Image.new("L", size, 0)
    sh.paste(alpha.point(lambda v: v * strength // 255), offset)
    return sh.filter(ImageFilter.GaussianBlur(blur))


def paste_rgba(dst: Image.Image, src: Image.Image, xy) -> None:
    layer = Image.new("RGBA", dst.size, (0, 0, 0, 0))
    layer.alpha_composite(src, xy)
    dst.paste(layer, (0, 0), layer)


def particles(img: Image.Image, n: int, seed: int, area=None) -> None:
    rng = random.Random(seed)
    w, h = img.size
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for _ in range(n):
        x, y = rng.uniform(0, w), rng.uniform(0, h)
        r = rng.uniform(.6, 2.2) * w / 1024
        d.ellipse([x - r, y - r, x + r, y + r], fill=(255, 255, 255, rng.randint(40, 140)))
    img.paste(layer.filter(ImageFilter.GaussianBlur(w / 1400)), (0, 0), layer.filter(ImageFilter.GaussianBlur(w / 1400)))


def ghost_plates(img: Image.Image, spots, seed: int) -> None:
    """Размытые номера по краям кадра — передний и дальний план."""
    texts = ["О000ОО 77", "Х999ХХ 99", "В001ОР 78", "М555ММ 50", "Е001КХ 777", "К100КК 77"]
    rng = random.Random(seed)
    for (x, y, wid, rot, blur, alpha) in spots:
        p = parse_ru(rng.choice(texts))
        hold = _holder(p, int(wid), "Номера", SILVER).rotate(rot, expand=True, resample=Image.BICUBIC)
        hold = hold.filter(ImageFilter.GaussianBlur(blur))
        a = hold.getchannel("A").point(lambda v: int(v * alpha))
        hold.putalpha(a)
        paste_rgba(img, hold, (int(x - hold.width / 2), int(y - hold.height / 2)))


def metal_text(text: str, size: int, top=(255, 255, 255), bottom=SILVER) -> Image.Image:
    """Заголовок: градиент сверху вниз, короткая выдавка, тонкая фаска."""
    f = ImageFont.truetype(TITLE_FONT, size)
    f.set_variation_by_name("Bold")
    l, t, r, b = f.getbbox(text)
    tw, th = r - l, b - t
    pad = int(size * .14)
    depth = max(2, int(th * .028))
    W, H = tw + pad * 2, th + pad * 2 + depth
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).text((pad - l, pad - t), text, font=f, fill=255)
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ext = Image.new("RGBA", (W, H), (40, 41, 46, 255))
    for k in range(depth, 0, -1):                                  # выдавка вниз
        shift = Image.new("L", (W, H), 0)
        shift.paste(mask, (0, k))
        out.paste(ext, (0, 0), shift)
    grad = Image.linear_gradient("L").resize((W, H))
    face = Image.composite(Image.new("RGB", (W, H), bottom), Image.new("RGB", (W, H), top), grad)
    face = face.convert("RGBA")
    out.paste(face, (0, 0), mask)
    edge = ImageChops.subtract(mask, ImageChops.offset(mask, 0, max(1, depth // 2)))  # светлая фаска сверху
    out.paste((255, 255, 255, 255), (0, 0), edge.point(lambda v: v * 160 // 255))
    return out


def orbit(size, center, rx, ry, rot, width, front: bool) -> Image.Image:
    """Половина хромового кольца: передняя (нижняя) или задняя (верхняя)."""
    w, h = size
    layer = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(layer)
    pts = []
    for k in range(361):
        a = math.radians(k)
        x, y = rx * math.cos(a), ry * math.sin(a)
        ca, sa = math.cos(math.radians(rot)), math.sin(math.radians(rot))
        pts.append((center[0] + x * ca - y * sa, center[1] + x * sa + y * ca, math.sin(a)))
    for i in range(360):
        x0, y0, s0 = pts[i]
        x1, y1, _ = pts[i + 1]
        if (s0 > 0) == front:
            fade = .35 + .65 * abs(math.cos(math.radians(i)))      # ярче по бокам, как блик на хроме
            d.line([(x0, y0), (x1, y1)], fill=int(255 * fade), width=width)
    return layer.filter(ImageFilter.GaussianBlur(width * .35))


# ------------------------------------------------------------ аватарка

def avatar(S: int = 2048) -> Image.Image:
    img = studio(S, S, spot=(.5, .46), spot_r=.48)
    # дальний план: размытые номера
    ghost_plates(img, [(S * .18, S * .14, S * .42, 9, S * .012, .38), (S * .86, S * .2, S * .36, -12, S * .014, .3),
                       (S * .12, S * .9, S * .5, -8, S * .02, .45), (S * .9, S * .86, S * .46, 10, S * .022, .4)], seed=7)
    # мягкий красный отблеск под героем
    glow = Image.new("L", (S, S), 0)
    ImageDraw.Draw(glow).ellipse([S * .2, S * .62, S * .8, S * .8], fill=95)
    img.paste(RED, (0, 0), glow.filter(ImageFilter.GaussianBlur(S * .07)))

    cx, cy = S // 2, int(S * .42)
    ring_back = orbit((S, S), (cx, cy + S * .04), S * .44, S * .11, -8, max(3, S // 340), front=False)
    img.paste((235, 237, 242), (0, 0), ring_back)

    title = metal_text("НОМЕРА", int(S * .27))
    scale = (S * .8) / title.width                                  # заголовок на 80% ширины
    title = title.resize((int(title.width * scale), int(title.height * scale)), Image.LANCZOS)
    tx, ty = cx - title.width // 2, cy - title.height // 2
    img.paste((0, 0, 0), (0, 0), drop_shadow(title.getchannel("A"), (S, S), (tx, ty + S // 60), S * .012, 190))
    paste_rgba(img, title, (tx, ty))

    # герой: номер в рамке заходит на нижнюю кромку букв и бросает на них тень
    hold = plate_holder(int(S * .74)).rotate(-5, expand=True, resample=Image.BICUBIC)
    hx, hy = cx - hold.width // 2, ty + int(title.height * .80)
    img.paste((0, 0, 0), (0, 0), drop_shadow(hold.getchannel("A"), (S, S), (hx, hy - S // 90), S * .018, 200))
    img.paste((0, 0, 0), (0, 0), drop_shadow(hold.getchannel("A"), (S, S), (hx, hy + S // 28), S * .03, 230))
    paste_rgba(img, hold, (hx, hy))

    ring_front = orbit((S, S), (cx, cy + S * .04), S * .44, S * .11, -8, max(3, S // 340), front=True)
    img.paste((245, 246, 250), (0, 0), ring_front)

    d = ImageDraw.Draw(img)
    for x, y, r in [(.79, .25, .028), (.21, .36, .018), (.83, .66, .016), (.27, .74, .012)]:   # 1–2 крупных блика и пара мелких
        _spark(d, S * x, S * y, S * r, (250, 250, 252))
    particles(img, 140, seed=3)
    return img


def circle_preview(img: Image.Image, size: int) -> Image.Image:
    small = img.resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size * 4 - 1, size * 4 - 1], fill=255)
    out = Image.new("RGB", (size, size), (24, 25, 29))
    out.paste(small, (0, 0), mask.resize((size, size), Image.LANCZOS))
    return out


# ------------------------------------------------------------ баннер описания

def banner(W: int = 1280, H: int = 720) -> Image.Image:
    img = studio(W, H, spot=(.5, .42), spot_r=.5)
    # дорога в перспективе, как на сцене мини-апы
    road = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(road)
    top, cx = int(H * .5), W // 2
    for k in range(8):
        t0, t1 = (k / 8) ** 1.8, ((k + .55) / 8) ** 1.8
        y0, y1 = top + (H - top) * t0, top + (H - top) * t1
        w0, w1 = 2 + 16 * t0, 2 + 16 * t1
        d.polygon([(cx - w0, y0), (cx + w0, y0), (cx + w1, y1), (cx - w1, y1)], fill=int(22 + 60 * t1))
    for side in (-1, 1):
        d.line([(cx + side * 160, top), (cx + side * 980, H)], fill=26, width=3)
    img.paste((255, 255, 255), (0, 0), road.filter(ImageFilter.GaussianBlur(1.2)))

    ghost_plates(img, [(W * .12, H * .24, W * .26, 8, 6, .35), (W * .9, H * .2, W * .24, -9, 7, .3),
                       (W * .08, H * .82, W * .3, -7, 10, .4), (W * .93, H * .84, W * .3, 9, 10, .38)], seed=11)

    glow = Image.new("L", (W, H), 0)
    ImageDraw.Draw(glow).ellipse([W * .28, H * .6, W * .72, H * .74], fill=130)
    img.paste(RED, (0, 0), glow.filter(ImageFilter.GaussianBlur(W * .04)))

    hold = plate_holder(int(W * .62))
    hx, hy = (W - hold.width) // 2, int(H * .25)
    img.paste((0, 0, 0), (0, 0), drop_shadow(hold.getchannel("A"), (W, H), (hx, hy + H // 26), W * .016, 235))
    refl = hold.transpose(Image.FLIP_TOP_BOTTOM).crop((0, 0, hold.width, int(hold.height * .45)))
    fade = Image.linear_gradient("L").resize(refl.size).point(lambda v: int((255 - v) * .18))
    refl.putalpha(ImageChops.multiply(refl.getchannel("A"), fade))
    paste_rgba(img, refl.filter(ImageFilter.GaussianBlur(2)), (hx, hy + hold.height + 8))
    paste_rgba(img, hold, (hx, hy))

    d = ImageDraw.Draw(img)
    rng = random.Random("A777AA")
    for _ in range(16):
        side = rng.choice((-1, 1))
        sx = hx + (-rng.randint(18, 150) if side < 0 else hold.width + rng.randint(18, 150))
        _spark(d, sx, hy + rng.randint(-30, hold.height + 20), rng.randint(5, 14), _mix(RED, (255, 255, 255), rng.random() * .6))

    _logo(d, 48, 40)
    f_title = font("display", 46)
    title = "Крути номера"
    d.text(((W - _tw(d, title, f_title)) // 2, int(H * .74)), title, font=f_title, fill=(242, 243, 245))
    f_sub = font("text", 25)
    sub = "Редкость и цена каждого номера · Россия и 19 стран"
    d.text(((W - _tw(d, sub, f_sub)) // 2, int(H * .74) + 66), sub, font=f_sub, fill=(150, 154, 163))
    tiers = ["#8E97A8", "#5FB2FF", "#7C6CFF", "#E85CFF", "#FFB020", "#FF3B3B"]
    bw, gap = 46, 7
    x0 = W - 48 - (bw * 6 + gap * 5)
    for i, c in enumerate(tiers):
        d.rounded_rectangle([x0 + i * (bw + gap), 58, x0 + i * (bw + gap) + bw, 65], radius=4, fill=c)
    particles(img, 70, seed=5)
    return img


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    a = avatar(2048)
    a.save(OUT / "avatar_2048.png", optimize=True)
    a.resize((1024, 1024), Image.LANCZOS).save(OUT / "avatar_1024.png", optimize=True)
    a.resize((640, 640), Image.LANCZOS).save(OUT / "avatar_640.png", optimize=True)
    circle_preview(a, 160).save(OUT / "_check_circle_160.png")
    circle_preview(a, 56).save(OUT / "_check_circle_56.png")
    b = banner(1280, 720)
    b.save(OUT / "banner_1280.png", optimize=True)
    b.resize((640, 360), Image.LANCZOS).save(OUT / "banner_640.png", optimize=True)
    print("ok", sorted(p.name for p in OUT.iterdir()))
