"""Скачать фотографии машин с Wikimedia Commons (свободные лицензии) в assets/cars/.

Запуск:  python tools/fetch_car_photos.py            — скачать недостающие
         python tools/fetch_car_photos.py bmw 2      — взять для bmw 3-й по счёту результат поиска
Авторы и лицензии записываются в assets/cars/CREDITS.md — их нужно сохранять.
"""
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "cars"
API = "https://commons.wikimedia.org/w/api.php"
UA = {"User-Agent": "plates-bot-assets/1.0 (car photos for a hobby game)"}
QUERIES = {
    "zhiguli": "VAZ-2107 front",
    "granta": "Lada Granta front",
    "camry": "Toyota Camry XV70 front",
    "bmw": "BMW M5 F90 front",
    "gelik": "Mercedes-AMG G 63 front",
    "porsche": "Porsche 992 Turbo S front",
    "lambo": "Lamborghini Huracan front",
    "rolls": "Rolls-Royce Phantom VIII front",
    "bugatti": "Bugatti Chiron front",
}
FREE = ("cc0", "cc by", "cc-by", "public domain", "pd")


def get(url: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
        return r.read()


def search(query: str) -> list[dict]:
    params = {"action": "query", "format": "json", "generator": "search", "gsrnamespace": 6, "gsrlimit": 12,
              "gsrsearch": query + " filetype:bitmap", "prop": "imageinfo",
              "iiprop": "url|size|extmetadata", "iiurlwidth": 1280}
    data = json.loads(get(API + "?" + urllib.parse.urlencode(params)))
    pages = sorted((data.get("query") or {}).get("pages", {}).values(), key=lambda p: p.get("index", 0))
    out = []
    for p in pages:
        ii = (p.get("imageinfo") or [{}])[0]
        meta = ii.get("extmetadata") or {}
        lic = (meta.get("LicenseShortName") or {}).get("value", "")
        if not any(k in lic.lower() for k in FREE):
            continue
        if ii.get("width", 0) < 1200 or ii.get("width", 0) < ii.get("height", 1) * 1.2:   # только широкие кадры
            continue
        author = re.sub(r"<[^>]+>", "", (meta.get("Artist") or {}).get("value", "")).strip()[:80]
        out.append({"title": p["title"], "thumb": ii.get("thumburl"), "license": lic, "author": author,
                    "page": ii.get("descriptionurl")})
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    credits_file = OUT / "credits.json"
    credits = json.loads(credits_file.read_text(encoding="utf-8")) if credits_file.exists() else {}
    only, pick = (sys.argv[1], int(sys.argv[2])) if len(sys.argv) > 2 else (None, 0)
    for car, query in QUERIES.items():
        if only and car != only:
            continue
        if not only and (OUT / f"{car}.jpg").exists():
            continue
        found = search(query)
        if len(found) <= (pick if only else 0):
            print(car, "— ничего подходящего")
            continue
        one = found[pick if only else 0]
        (OUT / f"{car}.jpg").write_bytes(get(one["thumb"]))
        credits[car] = {k: one[k] for k in ("title", "author", "license", "page")}
        print(car, "←", one["title"], "|", one["license"], "| вариантов:", len(found))
    from PIL import Image
    web = ROOT / "webapp" / "img" / "cars"
    web.mkdir(parents=True, exist_ok=True)
    for src in OUT.glob("*.jpg"):                 # лёгкие копии для мини-апы
        im = Image.open(src).convert("RGB")
        im.thumbnail((900, 900))
        im.save(web / src.name, quality=80, optimize=True)
    credits_file.write_text(json.dumps(credits, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = ["# Фотографии машин", "", "Снимки с Wikimedia Commons, лицензии сохранены.", ""]
    for car, c in credits.items():
        lines.append(f"- **{car}** — [{c['title']}]({c['page']}), автор: {c['author'] or 'не указан'}, лицензия: {c['license']}")
    (OUT / "CREDITS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
