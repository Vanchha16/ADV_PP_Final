"""Starter catalogue and fallback product images.

The catalogue lives in data/products.json (real sneakers researched online).
Photos are downloaded from each product's image_url; if a download fails the
product gets a simple generated image instead, so the shop never shows a blank.
"""
import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from sqlalchemy.exc import IntegrityError

from .extensions import db
from .models import AppMeta, Product

CATALOGUE = Path(__file__).resolve().parent.parent / "data" / "products.json"

# (background, text) pairs: soft tints that sit well on the white store layout.
PALETTES = [
    ("#eef2ff", "#3730a3"), ("#fdf2f8", "#9d174d"), ("#ecfdf5", "#065f46"),
    ("#fff7ed", "#9a3412"), ("#f0f9ff", "#075985"), ("#faf5ff", "#6b21a8"),
]


def _hex(c):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def _font(size, bold=True):
    names = (("DejaVuSans-Bold.ttf", "arialbd.ttf", "Arial Bold.ttf") if bold
             else ("DejaVuSans.ttf", "arial.ttf", "Arial.ttf"))
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def make_artwork(name, colors, label=None, category=None, size=800):
    """Plain placeholder: tinted square with a short label (model name) and category."""
    bg, fg = _hex(colors[0]), _hex(colors[1])
    img = Image.new("RGB", (size, size), bg)
    d = ImageDraw.Draw(img)
    label = (label or name.split()[0])[:12]
    fs = 120
    while fs > 40 and d.textlength(label, font=_font(fs)) > size * .8:
        fs -= 4
    d.text((size / 2, size * .47), label, font=_font(fs), fill=fg, anchor="mm")
    if category:
        d.text((size / 2, size * .47 + fs * .85), category, font=_font(34, bold=False), fill=fg, anchor="mm")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def seed_products(download_images=True):
    from .importer import import_file
    # Photos are fetched once on first start; failures fall back to generated images.
    result = import_file(CATALOGUE, download_images=download_images, timeout=8, log=lambda *_: None)
    return result["created"] + result["updated"]


def seed_if_empty(download_images=True):
    """Seed sample data once. Safe when several workers start at the same time."""
    try:
        db.session.add(AppMeta(key="seeded", value="1"))
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return  # another worker (or an earlier start) already did it
    if db.session.scalar(db.select(Product.id).limit(1)) is None:
        seed_products(download_images=download_images)
