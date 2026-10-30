"""Make the synthetic register pages used by `python tasks.py reader-eval` (pilot Part 5).

Every name, phone number and entry here is invented. The pages are drawn
from a fixed random seed, so the same files come out on every machine, and
each image has a `<stem>.expected.json` with the values a perfect reader
would return (after Vaari's normal validation). Only the `.expected.json`
files are committed; the images are made on demand and are git-ignored like
every register image.

The set is deliberately mixed, like a real Punjab register: Gurmukhi and
ASCII digits, acres written as "3.5", "੩.੫", "4 ਕਿੱਲੇ" or "2½", services in
Punjabi, English or both, dates as "18/10", "੧੮/੧੦" or "18 ਅਕਤੂਬਰ", some
blank harvest dates, a grey low-contrast background and a slight tilt.

    python scripts/make_synthetic_register_pages.py [OUT_DIR]

Needs a font with Gurmukhi (FreeSans, Lohit Gurmukhi or Noto Sans Gurmukhi).
Without one the pages still come out, with every cell in Latin script, and
the script says so.
"""

import json
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "examples" / "register_pages"
SEED = 20261030
PAGES = 6
ROWS_PER_PAGE = 8
YEAR = 2026
ANCHOR_TODAY = "2026-10-25"  # the eval validates dates as if this were today

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    "/usr/share/fonts/truetype/lohit-punjabi/Lohit-Gurmukhi.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansGurmukhi-Regular.ttf",
    "C:/Windows/Fonts/raavi.ttf",
    "/System/Library/Fonts/Supplemental/Gurmukhi Sangam MN.ttc",
]

GUR = str.maketrans("0123456789", "੦੧੨੩੪੫੬੭੮੯")
PA_MONTH = {10: "ਅਕਤੂਬਰ", 11: "ਨਵੰਬਰ"}

FIRST = ["Gurpreet", "Manjit", "Harjinder", "Sukhwinder", "Baljit", "Kuldeep", "Jaswant", "Amarjit",
         "Paramjit", "Rajinder", "Navdeep", "Satnam", "Lakhvir", "Inderjit", "Hardeep", "Charanjit"]
LAST = ["Singh", "Kaur", "Sandhu", "Gill", "Brar", "Dhillon", "Sidhu", "Mann"]
VILLAGES = ["Pind Kalan", "Bhucho Khurd", "Rampura Phul", "Kot Shamir", "Maur Mandi", "Sangat Kalan",
            "Talwandi Sabo", "Goniana Mandi"]
SERVICES = [
    ("super_seeder", ["Super Seeder", "ਸੁਪਰ ਸੀਡਰ", "ਸੁਪਰ seeder", "S.S."]),
    ("happy_seeder", ["Happy Seeder", "ਹੈਪੀ ਸੀਡਰ", "H.S."]),
    ("baler", ["Baler", "ਬੇਲਰ"]),
    ("mulcher", ["Mulcher", "ਮਲਚਰ"]),
]


def find_font(size: int) -> tuple[ImageFont.FreeTypeFont | ImageFont.ImageFont, bool]:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size), True
    return ImageFont.load_default(size=size), False


def make_row(rng: random.Random, page: int, row: int, gurmukhi_ok: bool) -> tuple[dict, dict]:
    """Return (what is written on the page, what a perfect reader returns)."""
    phone = f"90000{page:02d}{row:03d}"
    name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
    village = rng.choice(VILLAGES)
    acres_val = rng.choice([1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 6.0, 7.5])
    service, spellings = rng.choice(SERVICES)
    month = rng.choice([10, 10, 11])
    day = rng.randint(1, 28) if month == 11 else rng.randint(15, 31)
    blank_date = rng.random() < 0.15

    style = rng.random() if gurmukhi_ok else 0.0
    # Phone: ASCII, all Gurmukhi, or spaced
    if style > 0.66:
        w_phone = phone.translate(GUR)
    elif style > 0.33:
        w_phone = f"{phone[:5]} {phone[5:]}"
    else:
        w_phone = phone
    # Acres
    a_style = rng.random() if gurmukhi_ok else 0.0
    a_text = f"{acres_val:g}"
    if a_style > 0.75:
        w_acres = a_text.translate(GUR)
    elif a_style > 0.5:
        w_acres = f"{a_text} ਕਿੱਲੇ"
    elif a_style > 0.3 and acres_val % 1 == 0.5:
        w_acres = f"{int(acres_val)}½"
    else:
        w_acres = a_text
    # Service
    choices = spellings if gurmukhi_ok else [s for s in spellings if s.isascii()]
    w_service = rng.choice(choices)
    # Date
    d_style = rng.random() if gurmukhi_ok else 0.0
    if blank_date:
        w_date, iso = "", None
    else:
        iso = f"{YEAR}-{month:02d}-{day:02d}"
        if d_style > 0.66:
            w_date = f"{day} {PA_MONTH[month]}"
        elif d_style > 0.33:
            w_date = f"{day}/{month}".translate(GUR)
        else:
            w_date = f"{day}/{month}"

    written = {"phone": w_phone, "name": name, "village": village, "acres": w_acres,
               "service_type": w_service, "harvest_date": w_date}
    truth = {"phone": phone, "name": name, "village": village, "acres": acres_val,
             "service_type": service, "harvest_date": iso}
    return written, truth


def draw_page(rows: list[dict], page: int, rng: random.Random, font, small_font) -> Image.Image:
    w, h = 1600, 1100
    bg = rng.randint(168, 188)  # grey paper: low contrast on purpose
    img = Image.new("RGB", (w, h), (bg, bg - 6, bg - 16))
    d = ImageDraw.Draw(img)
    ink = (70, 70, 95)
    cols = [("#", 60), ("Phone / ਫ਼ੋਨ", 260), ("Name / ਨਾਮ", 280), ("Village / ਪਿੰਡ", 260),
            ("Acres / ਏਕੜ", 170), ("Machine / ਮਸ਼ੀਨ", 250), ("Harvest / ਕਟਾਈ", 220)]
    x0, y0, row_h = 40, 120, 100
    d.text((x0, 40), f"Booking register (SYNTHETIC TEST PAGE {page}) / ਬੁਕਿੰਗ ਰਜਿਸਟਰ", fill=ink, font=font)
    xs = [x0]
    for _, cw in cols:
        xs.append(xs[-1] + cw)
    for i, (title, _) in enumerate(cols):
        d.text((xs[i] + 8, y0 + 30), title, fill=ink, font=small_font)
    for r in range(len(rows) + 2):
        d.line([(x0, y0 + r * row_h), (xs[-1], y0 + r * row_h)], fill=ink, width=2)
    for x in xs:
        d.line([(x, y0), (x, y0 + (len(rows) + 1) * row_h)], fill=ink, width=2)
    keys = ["phone", "name", "village", "acres", "service_type", "harvest_date"]
    for i, written in enumerate(rows, start=1):
        y = y0 + i * row_h + 30 + rng.randint(-6, 6)
        d.text((xs[0] + 12, y), str(i), fill=ink, font=font)
        for j, k in enumerate(keys, start=1):
            d.text((xs[j] + 10 + rng.randint(-4, 4), y), written[k], fill=ink, font=font)
    img = img.rotate(rng.uniform(-1.5, 1.5), expand=False, fillcolor=(bg, bg - 6, bg - 16))
    return img.filter(ImageFilter.GaussianBlur(0.6))


def generate(out_dir: Path = OUT_DIR, force: bool = False) -> list[Path]:
    """Write synth_01..06.jpg and .expected.json into out_dir. Returns the image paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    font, gurmukhi_ok = find_font(34)
    small, _ = find_font(24)
    if not gurmukhi_ok:
        print("No Gurmukhi font found: pages are drawn in Latin script only.")
    rng = random.Random(SEED)
    images = []
    for p in range(1, PAGES + 1):
        stem = f"synth_{p:02d}"
        written, truth = zip(*(make_row(rng, p, r, gurmukhi_ok) for r in range(1, ROWS_PER_PAGE + 1)), strict=True)
        page_img = draw_page(list(written), p, rng, font, small)
        img_path = out_dir / f"{stem}.jpg"
        if force or not img_path.exists():
            page_img.save(img_path, format="JPEG", quality=85)
        expected = {
            "synthetic": True,
            "anchor_today": ANCHOR_TODAY,
            "gurmukhi_font": gurmukhi_ok,
            "rows": [{"row": i, "written": w, "fields": t} for i, (w, t) in enumerate(zip(written, truth, strict=True), start=1)],
        }
        (out_dir / f"{stem}.expected.json").write_text(
            json.dumps(expected, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        images.append(img_path)
    return images


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else OUT_DIR
    for path in generate(target, force=True):
        print(f"Wrote {path}")
