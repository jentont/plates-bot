"""Рендер карточки номера в PNG (Pillow) для сообщений в чате и inline-режима.

Мир карточки тот же, что в мини-апе: ночной асфальт, номер в чёрной рамке,
цвет несёт только редкость (тонкий кант, подпись на рамке, отблеск на земле).
"""
from __future__ import annotations

import io
import random
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from core.plates import Plate
from core.rarity import Evaluation, format_price

W, H = 1200, 675
TEXT = (242, 243, 245)
TEXT2 = (201, 204, 210)
MUTED = (139, 143, 152)
PLATE_WHITE = (243, 243, 239)
INK = (19, 19, 19)

ROOT = Path(__file__).resolve().parent.parent
FONT_DIRS = [ROOT / "assets" / "fonts", ROOT / "webapp" / "fonts", Path("C:/Windows/Fonts"),
             Path("/usr/share/fonts/opentype/noto"), Path("/usr/share/fonts/truetype/noto"),
             Path("/usr/share/fonts/truetype/dejavu"), Path("/System/Library/Fonts")]
FONTS = {
    "display": ["Unbounded-Bold.ttf", "Manrope-Bold.ttf", "DejaVuSans-Bold.ttf"],
    "black": ["Unbounded-Black.ttf", "Unbounded-Bold.ttf", "Manrope-Bold.ttf", "DejaVuSans-Bold.ttf"],
    "bold": ["Manrope-Bold.ttf", "DejaVuSans-Bold.ttf"],
    "text": ["Manrope-Medium.ttf", "Manrope-Bold.ttf", "DejaVuSans.ttf"],
    "plate": ["Barlow-Bold.ttf", "bahnschrift.ttf", "Manrope-Bold.ttf", "DejaVuSans-Bold.ttf"],
    "cjk": ["msyhbd.ttc", "msyh.ttc", "malgunbd.ttf", "malgun.ttf", "NotoSansCJK-Bold.ttc", "NotoSansCJK-Regular.ttc",
            "PingFang.ttc", "Manrope-Bold.ttf"],
    "kr": ["malgunbd.ttf", "malgun.ttf", "NotoSansCJK-Bold.ttc", "NotoSansCJK-Regular.ttc", "msyhbd.ttc", "Manrope-Bold.ttf"],
}
# Шрифт номера без кириллицы: русские буквы номеров рисуем латинскими двойниками
CYR2LAT = str.maketrans("АВЕКМНОРСТУХ", "ABEKMHOPCTYX")


@lru_cache(maxsize=128)
def font(kind: str, size: int):
    for name in FONTS[kind]:
        for d in FONT_DIRS:
            p = d / name
            if p.exists():
                try:
                    return ImageFont.truetype(str(p), size)
                except OSError:
                    continue
    return ImageFont.load_default(size)


def _hex(c: str) -> tuple[int, int, int]:
    c = c.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def _mix(a, b, k: float):
    return tuple(int(a[i] + (b[i] - a[i]) * k) for i in range(3))


def _tw(draw, text: str, f) -> int:
    return int(draw.textlength(text, font=f))


def _fit(draw, text: str, kind: str, size: int, max_w: int, min_size: int = 14):
    f = font(kind, size)
    while _tw(draw, text, f) > max_w and size > min_size:
        size -= 2
        f = font(kind, size)
    return f


def _ellipsis(draw, text: str, f, max_w: int) -> str:
    if _tw(draw, text, f) <= max_w:
        return text
    while text and _tw(draw, text + "…", f) > max_w:
        text = text[:-1]
    return text.rstrip() + "…"


# ------------------------------------------------------------ фон

@lru_cache(maxsize=1)
def _background() -> Image.Image:
    """Асфальт: зерно, свет от фар по центру, виньетка, разметка в перспективе."""
    base = Image.new("RGB", (W, H), (7, 7, 8))
    light = Image.new("RGB", (W, H), (36, 37, 42))
    mask = ImageChops.invert(Image.radial_gradient("L").resize((W, int(H * 1.5)))).crop((0, int(H * .12), W, int(H * .12) + H))
    img = Image.composite(light, base, mask.point(lambda v: int(v * .9)))
    noise = Image.effect_noise((W, H), 22).convert("RGB")
    img = Image.blend(img, ImageChops.multiply(img, noise), .5)
    road = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(road)
    cx, top, bottom = W // 2, 300, H
    for k in range(7):                                   # прерывистая осевая, сужается к горизонту
        t0, t1 = (k / 7) ** 1.8, ((k + .55) / 7) ** 1.8
        y0, y1 = top + (bottom - top) * t0, top + (bottom - top) * t1
        w0, w1 = 2 + 16 * t0, 2 + 16 * t1
        d.polygon([(cx - w0, y0), (cx + w0, y0), (cx + w1, y1), (cx - w1, y1)], fill=int(26 + 60 * t1))
    for side in (-1, 1):                                 # кромки полосы
        d.line([(cx + side * 150, top), (cx + side * 900, bottom)], fill=30, width=3)
    road = road.filter(ImageFilter.GaussianBlur(1.2))
    img.paste((255, 255, 255), (0, 0), road)
    return img


# ------------------------------------------------------------ номер

def _emboss(draw, xy, text, f, ink):
    x, y = xy
    draw.text((x, y + 2), text, font=f, fill=(255, 255, 255))
    draw.text((x, y), text, font=f, fill=ink)


def _centered(draw, box, text, f, ink, emboss=True):
    x, y, w, h = box
    l, t, r, b = draw.textbbox((0, 0), text, font=f)
    pos = (x + (w - (r - l)) // 2 - l, y + (h - (b - t)) // 2 - t)
    (_emboss if emboss else lambda d, p, s, ff, c: d.text(p, s, font=ff, fill=c))(draw, pos, text, f, ink)


def _flag(draw, x, y, w, h, country):
    stripes = {
        "RU": [(255, 255, 255), (0, 57, 166), (213, 43, 30)], "UA": [(31, 95, 191), (244, 206, 27)],
        "BY": [(200, 49, 62), (200, 49, 62), (74, 166, 87)], "DE": [(0, 0, 0), (221, 0, 0), (255, 206, 0)],
        "AM": [(217, 0, 18), (0, 51, 160), (242, 168, 0)], "UZ": [(0, 153, 181), (255, 255, 255), (30, 181, 58)],
        "PL": [(255, 255, 255), (220, 20, 60)], "ES": [(170, 21, 27), (241, 191, 0), (170, 21, 27)],
        "KZ": [(0, 175, 202)], "TR": [(227, 10, 23)], "GE": [(255, 255, 255), (255, 60, 60), (255, 255, 255)],
    }.get(country)
    if not stripes:
        vertical = {"FR": [(0, 85, 164), (255, 255, 255), (239, 65, 53)], "IT": [(0, 146, 70), (255, 255, 255), (206, 43, 55)]}.get(country)
        if vertical:
            sw = w / 3
            for i, c in enumerate(vertical):
                draw.rectangle([x + i * sw, y, x + (i + 1) * sw, y + h], fill=c)
        return
    sh = h / len(stripes)
    for i, c in enumerate(stripes):
        draw.rectangle([x, y + i * sh, x + w, y + (i + 1) * sh], fill=c)


def _plate_image(plate: Plate, w: int) -> Image.Image:
    """Номер как отдельная картинка RGBA шириной w."""
    h = int(w / 4.64)
    bg, ink, border = PLATE_WHITE, INK, (13, 13, 13)
    st = plate.style
    if st == "gb":
        bg = (246, 199, 0)
    if st == "cn":
        bg, ink, border = (14, 70, 180), (255, 255, 255), (255, 255, 255)
    if st == "jp":
        ink = (23, 112, 58)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    bw, rad = max(4, w // 130), int(w * .024)
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=rad, fill=bg, outline=border, width=bw)
    # объём: светлая кромка сверху, тень снизу
    shade = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shade)
    for i in range(int(h * .32)):
        sd.line([(bw, h - bw - i), (w - bw, h - bw - i)], fill=(0, 0, 0, int(34 * (1 - i / (h * .32)))))
    sd.line([(rad, bw + 1), (w - rad, bw + 1)], fill=(255, 255, 255, 200), width=2)
    img.alpha_composite(shade)
    d = ImageDraw.Draw(img)
    emboss = st not in ("cn", "jp")

    if st == "ru":
        p = plate.parts
        reg_w = int(w * .235)
        d.line([(w - reg_w, 0), (w - reg_w, h)], fill=border, width=bw)
        f_d, f_l = font("plate", int(h * .86)), font("plate", int(h * .69))
        parts = [(p["l1"].translate(CYR2LAT), f_l), (p["digits"], f_d), ((p["l2"] + p["l3"]).translate(CYR2LAT), f_l)]
        gap = int(w * .028)
        total = sum(_tw(d, t, f) for t, f in parts) + gap * 2
        x = (w - reg_w - total) // 2
        base = int(h * .5 + f_d.getbbox("0")[3] * .5 - f_d.getbbox("0")[1] * .5)      # общая базовая линия
        for t, f in parts:
            _emboss(d, (x, base - f.getbbox("0")[3]), t, f, ink)
            x += _tw(d, t, f) + gap
        f_r = font("plate", int(h * .58))
        rx = w - reg_w
        _centered(d, (rx, int(h * .06), reg_w, int(h * .56)), p["region"], f_r, ink)
        f_rus = font("plate", int(h * .2))
        rus_w, fw, fh = _tw(d, "RUS", f_rus), int(h * .27), int(h * .16)
        sx = rx + (reg_w - rus_w - fw - 8) // 2
        d.text((sx, int(h * .69)), "RUS", font=f_rus, fill=ink)
        _flag(d, sx + rus_w + 8, int(h * .73), fw, fh, "RU")
        d.rectangle([sx + rus_w + 8, int(h * .73), sx + rus_w + 8 + fw, int(h * .73) + fh], outline=(60, 60, 60), width=1)
        return img

    text, strip, top_pad = plate.text, 0, 0
    if st in ("eu", "ua", "kz", "uz", "ge", "am", "by"):
        strip = int(w * .105)
        color = {"ua": (31, 95, 191), "by": bg}.get(st, (10, 58, 154))
        d.rounded_rectangle([bw, bw, strip, h - bw - 1], radius=max(2, rad - bw), fill=color)
        d.rectangle([strip - rad, bw, strip, h - bw - 1], fill=color)
        if st == "ua":
            d.rectangle([bw, h // 2, strip, h - bw - rad], fill=(244, 206, 27))
        if st == "by":
            d.line([(strip, bw), (strip, h - bw)], fill=border, width=max(2, bw // 2))
        f_cc = font("plate", int(h * .24))
        d.text((bw + (strip - bw - _tw(d, plate.country, f_cc)) // 2, int(h * .66)), plate.country, font=f_cc,
               fill=ink if st == "by" else (255, 255, 255))
        fw = int(strip * .56)
        _flag(d, bw + (strip - bw - fw) // 2, int(h * .2), fw, int(fw * .66), plate.country)
    elif st == "ae":
        strip = int(w * .24)
        d.rounded_rectangle([bw, bw, strip, h - bw - 1], radius=max(2, rad - bw), fill=(200, 32, 42))
        d.rectangle([strip - rad, bw, strip, h - bw - 1], fill=(200, 32, 42))
        name = plate.parts["emirate"].upper()
        _centered(d, (bw, 0, strip - bw, h), name, _fit(d, name, "plate", int(h * .3), strip - bw - 16), (255, 255, 255), emboss=False)
        text = f"{plate.parts['code']} {plate.parts['num']}"
    elif st == "us":
        state = (plate.region_name or "").upper()
        f_s = font("plate", int(h * .2))
        d.text(((w - _tw(d, state, f_s)) // 2, int(h * .08)), state, font=f_s, fill=(27, 77, 177))
        top_pad = int(h * .2)
    kind = "cjk" if st in ("cn", "jp") else "kr" if st == "kr" else "plate"
    f = _fit(d, text, kind, int(h * (.78 if kind == "plate" else .6)), int((w - strip) * .9))
    _centered(d, (strip, top_pad, w - strip, h - top_pad), text.translate(CYR2LAT) if kind == "plate" else text, f, ink, emboss)
    return img


def _holder(plate: Plate, w: int, lip: str, color) -> Image.Image:
    """Номер в чёрной рамке с болтами, бликом и подписью на нижней планке."""
    pad, lip_h = int(w * .022), int(w * .07)
    pw = w - pad * 2
    pl = _plate_image(plate, pw)
    h = pad + pl.height + lip_h
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    rad = int(w * .036)
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=rad, fill=(14, 15, 17), outline=(0, 0, 0), width=3)
    d.rounded_rectangle([3, 3, w - 4, int(h * .5)], radius=rad, outline=(74, 76, 84), width=2)
    d.rectangle([4, int(h * .2), w - 5, h - 8], fill=(14, 15, 17))
    img.alpha_composite(pl, (pad, pad))
    d = ImageDraw.Draw(img)
    f = _fit(d, lip.upper(), "display", int(lip_h * .42), w // 2)
    lw = _tw(d, lip.upper(), f)
    ly = pad + pl.height
    _centered(d, (0, ly, w, lip_h), lip.upper(), f, color, emboss=False)
    for bx in ((w - lw) // 2 - 26, (w + lw) // 2 + 26):   # болты по бокам подписи
        cy = ly + lip_h // 2
        d.ellipse([bx - 6, cy - 6, bx + 6, cy + 6], fill=(58, 59, 64))
        d.ellipse([bx - 4, cy - 5, bx + 1, cy], fill=(150, 152, 160))
    # диагональный блик
    glare = Image.new("L", (w, h), 0)
    gd = ImageDraw.Draw(glare)
    gx = int(w * .62)
    gd.polygon([(gx, 0), (gx + int(w * .09), 0), (gx - int(w * .05), h), (gx - int(w * .14), h)], fill=70)
    glare = glare.filter(ImageFilter.GaussianBlur(14))
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=rad, fill=255)
    img.paste((255, 255, 255), (0, 0), ImageChops.multiply(glare, mask))
    return img


def _place_holder(img: Image.Image, holder: Image.Image, x: int, y: int, tint) -> None:
    """Ставит рамку на асфальт: тень, цветной отблеск редкости и отражение."""
    w, h = holder.size
    shadow = Image.new("L", (W, H), 0)
    ImageDraw.Draw(shadow).ellipse([x + 20, y + h - 6, x + w - 20, y + h + 46], fill=235)
    img.paste((0, 0, 0), (0, 0), shadow.filter(ImageFilter.GaussianBlur(20)))
    glow = Image.new("L", (W, H), 0)
    ImageDraw.Draw(glow).ellipse([x + 90, y + h + 8, x + w - 90, y + h + 40], fill=120)
    img.paste(tint, (0, 0), glow.filter(ImageFilter.GaussianBlur(26)))
    refl = holder.transpose(Image.FLIP_TOP_BOTTOM).crop((0, 0, w, 70))
    fade = Image.linear_gradient("L").resize((w, 70)).point(lambda v: int((255 - v) * .16))
    refl.putalpha(ImageChops.multiply(refl.getchannel("A"), fade))
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    layer.alpha_composite(refl.filter(ImageFilter.GaussianBlur(2)), (x, y + h + 6))
    layer.alpha_composite(holder, (x, y))
    img.paste(layer, (0, 0), layer)


def _logo(draw, x: int, y: int) -> None:
    f, f2 = font("black", 22), font("plate", 28)
    w1, w2 = _tw(draw, "НОМЕРА", f) + 30, _tw(draw, "777", f2) + 22
    draw.rounded_rectangle([x, y, x + w1 + w2, y + 46], radius=9, fill=PLATE_WHITE, outline=(13, 13, 13), width=3)
    draw.rounded_rectangle([x - 2, y - 2, x + w1 + w2 + 2, y + 48], radius=11, outline=(70, 72, 78), width=1)
    draw.line([(x + w1, y), (x + w1, y + 46)], fill=(13, 13, 13), width=3)
    _centered(draw, (x, y, w1, 46), "НОМЕРА", f, INK, emboss=False)
    _centered(draw, (x + w1, y, w2, 46), "777", f2, INK, emboss=False)


def _spark(draw, x, y, r, color):
    draw.polygon([(x, y - r), (x + r * .22, y - r * .22), (x + r, y), (x + r * .22, y + r * .22),
                  (x, y + r), (x - r * .22, y + r * .22), (x - r, y), (x - r * .22, y - r * .22)], fill=color)


def _frame(img: Image.Image, color=None) -> ImageDraw.ImageDraw:
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([14, 14, W - 15, H - 15], radius=30, outline=(52, 54, 60), width=2)
    if color:
        d.rounded_rectangle([22, 22, W - 23, H - 23], radius=24, outline=_mix((10, 10, 12), color, .55), width=2)
    return d


def _png(img: Image.Image) -> bytes:
    out = io.BytesIO()
    img.save(out, "PNG", compress_level=6)
    return out.getvalue()


# ------------------------------------------------------------ карточки

def draw_plate(img: Image.Image, plate: Plate, box: tuple[int, int, int, int]) -> None:
    """Совместимость: рисует номер без рамки в прямоугольнике box=(x, y, w, h)."""
    x, y, w, _ = box
    pl = _plate_image(plate, w)
    img.paste(pl, (x, y), pl)


def render_card(plate: Plate, ev: Evaluation, title: str, user_name: str, bot_name: str,
                country_name: str, footer: str = "") -> bytes:
    color = _hex(ev.tier_color)
    special = ev.score >= 62
    img = _background().copy()
    d = _frame(img, color if special else None)

    _logo(d, 60, 52)
    f_small = font("text", 24)
    where = country_name + (f" · {plate.region_name}" if plate.region_name and plate.region_name != country_name else "")
    where = _ellipsis(d, where, f_small, 560)
    d.text((W - 60 - _tw(d, where, f_small), 62), where, font=f_small, fill=MUTED)

    holder = _holder(plate, 760, ev.tier_name, color)
    hx, hy = (W - holder.width) // 2, 128
    _place_holder(img, holder, hx, hy, color)
    d = ImageDraw.Draw(img)

    if special:                                           # редким номерам — искры вокруг
        rng = random.Random(plate.text)
        for _ in range(22 if ev.score >= 80 else 12):
            side = rng.choice((-1, 1))
            sx = hx + (-rng.randint(20, 190) if side < 0 else holder.width + rng.randint(20, 190))
            _spark(d, sx, hy + rng.randint(-40, holder.height + 30), rng.randint(5, 15), _mix(color, (255, 255, 255), rng.random() * .6))

    # слева: редкость и цена
    y0 = 420
    f_tier = font("bold", 30)
    d.ellipse([60, y0 + 12, 78, y0 + 30], fill=color)
    d.text((92, y0), ev.tier_name, font=f_tier, fill=color)
    meta = (f"топ {ev.percentile or 0.01}%  ·  " if ev.percentile <= 50 else "") + f"{ev.score} очков"
    d.text((92 + _tw(d, ev.tier_name, f_tier) + 22, y0 + 6), meta, font=f_small, fill=MUTED)
    price = format_price(ev, plate.country)
    f_price = _fit(d, price, "display", 70, 560)
    d.text((58, y0 + 56), price, font=f_price, fill=TEXT if ev.price_rub else MUTED)
    # шкала из шести уровней
    tiers = ["#8E97A8", "#5FB2FF", "#7C6CFF", "#E85CFF", "#FFB020", "#FF3B3B"]
    idx = max(i for i, c in enumerate(tiers) if c.lower() == ev.tier_color.lower()) if ev.tier_color.upper() in [c.upper() for c in tiers] else 0
    for i, c in enumerate(tiers):
        d.rounded_rectangle([60 + i * 62, y0 + 152, 60 + i * 62 + 54, y0 + 159], radius=4, fill=_hex(c) if i <= idx else (40, 41, 46))

    # справа: причины
    reasons = [r for r in ev.reasons if r["points"]][:3]
    f_reason, f_pts = font("text", 25), font("bold", 25)
    rx0, rx1 = 690, W - 60
    ry = y0 + (0 if len(reasons) == 3 else 26)
    if not reasons:
        d.text((rx1 - _tw(d, "Без особых признаков", f_reason), ry + 26), "Без особых признаков", font=f_reason, fill=MUTED)
    for i, r in enumerate(reasons):
        pts = f"+{r['points']}"
        pw = _tw(d, pts, f_pts)
        title_txt = _ellipsis(d, r["title"], f_reason, rx1 - rx0 - pw - 24)
        d.text((rx0, ry), title_txt, font=f_reason, fill=TEXT2)
        d.text((rx1 - pw, ry), pts, font=f_pts, fill=color)
        if i < len(reasons) - 1:
            d.line([(rx0, ry + 44), (rx1, ry + 44)], fill=(48, 50, 56), width=1)
        ry += 56

    f_foot = font("text", 23)
    name = _ellipsis(d, user_name or "Игрок", f_foot, 420)
    d.text((60, H - 70), f"{title} · {name}" if title else name, font=f_foot, fill=MUTED)
    tag = footer or f"@{bot_name}"
    d.text((W - 60 - _tw(d, tag, f_foot), H - 70), tag, font=f_foot, fill=MUTED)
    return _png(img)


def render_cover(bot_name: str, subtitle: str) -> bytes:
    """Обложка для inline-результата до того, как номер выпал."""
    img = _background().copy()
    d = _frame(img)
    _logo(d, 60, 52)
    blank = Plate(country="RU", text="? ??? ?? ??", parts={"l1": "?", "digits": "???", "l2": "?", "l3": "?", "region": "??"}, style="ru")
    holder = _holder(blank, 760, "· · ·", MUTED)
    _place_holder(img, holder, (W - holder.width) // 2, 150, (90, 92, 100))
    d = ImageDraw.Draw(img)
    f_title = _fit(d, subtitle, "display", 40, W - 160)
    d.text(((W - _tw(d, subtitle, f_title)) // 2, 468), subtitle, font=f_title, fill=TEXT)
    f_small = font("text", 26)
    hint = "Нажми «Крутить» — номер упадёт сюда"
    d.text(((W - _tw(d, hint, f_small)) // 2, 532), hint, font=f_small, fill=MUTED)
    tag = f"@{bot_name}"
    d.text((W - 60 - _tw(d, tag, font("text", 23)), H - 70), tag, font=font("text", 23), fill=MUTED)
    return _png(img)
