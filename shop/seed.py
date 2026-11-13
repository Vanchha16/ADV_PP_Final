"""Sample anime-merch catalogue with generated product artwork (no external files needed)."""
import io
from decimal import Decimal

from PIL import Image, ImageDraw, ImageFont

from .extensions import db
from sqlalchemy.exc import IntegrityError

from .models import AppMeta, Product

SAMPLES = [
    ("Ninja Hero Action Figure", "29.99", 20, True, ("#f97316", "#7c2d12"),
     "Fully articulated 18 cm PVC figure of a spiky-haired ninja hero, with three "
     "swappable faces, two hand-sign hands, a kunai and a display stand. Comes in a "
     "window box, perfect for your shelf."),
    ("Kawaii Neko Plush", "14.50", 35, True, ("#f9a8d4", "#be185d"),
     "Super-soft 30 cm cat plush with embroidered sparkly eyes and a tiny bell collar. "
     "Huggable, washable and ready to guard your bed."),
    ("Shonen Manga Box Set Vol. 1-5", "39.00", 12, True, ("#1e293b", "#dc2626"),
     "The first five volumes of an epic shonen adventure in one collector's box, "
     "with an exclusive double-sided poster. English edition, about 950 pages."),
    ("Sakura Anime Hoodie", "34.00", 18, True, ("#fbcfe8", "#db2777"),
     "Cozy cotton-blend hoodie with a cherry-blossom back print and a kanji "
     "sleeve design. Unisex fit, sizes S-XXL (choose at delivery)."),
    ("Chibi Acrylic Keychain Set", "7.50", 60, True, ("#a5f3fc", "#0e7490"),
     "Set of 4 double-sided acrylic keychains with cute chibi characters. "
     "6 cm each, with metal clasps. Great for bags and gifts."),
    ("Mecha Robot Model Kit 1/144", "24.00", 0, True, ("#94a3b8", "#1e3a8a"),
     "Snap-fit 1/144 scale giant-robot model kit, with no glue or paint needed. "
     "Includes beam rifle, shield and decals. Back in stock soon!"),
    ("Anime Art Poster Pack", "12.00", 40, True, ("#fde68a", "#7c3aed"),
     "Five A3 art prints on 200 gsm matte paper: sunset rooftops, spirit forest, "
     "neon city, ocean train and starry festival scenes."),
    ("Magical Girl Wand Replica", "19.90", 8, True, ("#e9d5ff", "#9333ea"),
     "35 cm light-up transformation wand with heart crystal, sound effects and "
     "rainbow LEDs. Batteries included."),
    ("Limited Collector Figure Box", "89.00", 3, False, ("#111827", "#facc15"),
     "Numbered limited-edition premium figure set with a certificate. Inactive until "
     "pre-orders open, shown here to demonstrate the Active/Inactive status."),
]


def _hex(c):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def _font(size):
    for name in ("DejaVuSans-Bold.ttf", "Arial Bold.ttf", "arialbd.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def make_artwork(name, colors, size=800):
    top, bottom = _hex(colors[0]), _hex(colors[1])
    # Flat, single-colour background (no gradients) with a white badge.
    img = Image.new("RGB", (size, size), bottom)
    draw = ImageDraw.Draw(img)
    draw.ellipse((size * .25, size * .2, size * .75, size * .7), fill=(255, 255, 255))
    lum = lambda c: 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]
    dark = min(top, bottom, key=lum)
    initials = "".join(w[0] for w in name.split()[:2]).upper()
    draw.text((size / 2, size * .45), initials, font=_font(150), fill=dark, anchor="mm")
    font_size = 46
    while font_size > 22 and draw.textlength(name, font=_font(font_size)) > size * .88:
        font_size -= 2
    draw.text((size / 2, size * .84), name, font=_font(font_size), fill=(255, 255, 255),
              anchor="mm", stroke_width=3, stroke_fill=dark)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return buf.getvalue()


def seed_products():
    for name, price, stock, active, colors, desc in SAMPLES:
        db.session.add(Product(name=name, description=desc, price=Decimal(price), stock=stock,
                               is_active=active, image_data=make_artwork(name, colors),
                               image_mime="image/jpeg"))
    db.session.commit()
    return len(SAMPLES)


def seed_if_empty():
    """Seed sample data once. Safe when several workers start at the same time."""
    try:
        db.session.add(AppMeta(key="seeded", value="1"))
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return  # another worker (or an earlier start) already did it
    if db.session.scalar(db.select(Product.id).limit(1)) is None:
        seed_products()
