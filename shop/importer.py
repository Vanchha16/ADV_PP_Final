"""Import products from a JSON or CSV file.

Run:  flask --app wsgi import-products data/products.json [--replace] [--no-download-images]

JSON: {"products": [{...}, ...]}  or a plain list of objects.
CSV:  a header row with the same field names.

Fields: name (required), price (required), stock, category, description, active,
        image_url, crop (pad | left | center | right, for wide photos), label, source.
crop "pad" puts a wide photo on a white square so nothing is cut off (best for shoes).
label is the short text drawn on the fallback image (older files may call it character).
Products are matched by name: an existing product is updated, a new one is created.
"""
import csv
import io
import json
import zlib
from decimal import Decimal, InvalidOperation
from pathlib import Path

import requests
from PIL import Image

from .extensions import db
from .images import ImageError, process_stream
from .models import OrderItem, Product
from .seed import PALETTES, make_artwork

MAX_DOWNLOAD = 8 * 1024 * 1024
TRUE = {"1", "true", "yes", "y", "on", "active"}
USER_AGENT = "Mozilla/5.0 (compatible; SneakerWorld-importer/1.0)"


def load_rows(path):
    path = Path(path)
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".csv":
        return list(csv.DictReader(io.StringIO(text)))
    data = json.loads(text)
    return data["products"] if isinstance(data, dict) else data


def _bool(value, default=True):
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in TRUE


def _palette(name):
    # Stable pick so re-imports keep the same artwork.
    return PALETTES[zlib.crc32(name.encode()) % len(PALETTES)]


def _crop_square(body, where):
    """Make a wide photo square: pad it onto white, or cut the left, center or right part."""
    img = Image.open(body)
    img.load()
    w, h = img.size
    if w <= h * 1.1:
        body.seek(0)
        return body
    if where == "pad":
        side = round(w * 1.08)  # small margin so the shoe doesn't touch the card edge
        square = Image.new("RGB", (side, side), (255, 255, 255))
        square.paste(img.convert("RGB"), ((side - w) // 2, (side - h) // 2))
        img = square
    else:
        x = {"left": 0, "right": w - h}.get(where, (w - h) // 2)
        img = img.crop((x, 0, x + h, h))
    out = io.BytesIO()
    img.save(out, format="PNG")
    out.seek(0)
    return out


def download_image(url, crop=None, timeout=20):
    r = requests.get(url, timeout=timeout, stream=True, headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    body = io.BytesIO()
    for chunk in r.iter_content(64 * 1024):
        body.write(chunk)
        if body.tell() > MAX_DOWNLOAD:
            raise ImageError("image is larger than 8 MB")
    body.seek(0)
    if crop:
        body = _crop_square(body, crop)
    return process_stream(body)


def validate(row):
    name = str(row.get("name") or "").strip()
    if not 1 <= len(name) <= 120:
        raise ValueError("name is required (max 120 characters)")
    try:
        price = Decimal(str(row.get("price"))).quantize(Decimal("0.01"))
    except InvalidOperation:
        raise ValueError(f"{name}: price {row.get('price')!r} is not a number")
    if price <= 0:
        raise ValueError(f"{name}: price must be greater than 0")
    try:
        stock = int(row.get("stock") or 0)
    except ValueError:
        raise ValueError(f"{name}: stock {row.get('stock')!r} is not a whole number")
    return name, price, max(stock, 0)


def import_rows(rows, replace=False, download_images=True, log=print, timeout=20):
    result = {"created": 0, "updated": 0, "deleted": 0, "errors": []}
    if replace:
        db.session.execute(db.update(OrderItem).values(product_id=None))  # keep order history
        result["deleted"] = db.session.execute(db.delete(Product)).rowcount
        db.session.commit()

    # The shop lists newest first, so insert in reverse to keep the file's order.
    for row in reversed(rows):
        try:
            name, price, stock = validate(row)
        except ValueError as exc:
            result["errors"].append(str(exc))
            continue
        product = db.session.scalar(db.select(Product).where(Product.name == name))
        is_new = product is None
        if is_new:
            product = Product(name=name)
            db.session.add(product)
        product.price = price
        product.stock = stock
        product.category = str(row.get("category") or "").strip() or None
        product.description = str(row.get("description") or "").strip()
        product.is_active = _bool(row.get("active"), default=True)

        image_url = str(row.get("image_url") or "").strip()
        if image_url and download_images:
            crop = str(row.get("crop") or "").strip().lower() or None
            try:
                product.image_data, product.image_mime = download_image(image_url, crop=crop, timeout=timeout)
                product.image_url = None
            except (requests.RequestException, ImageError, OSError) as exc:
                result["errors"].append(f"{name}: image download failed ({exc}); using a generated image")
                image_url = ""
        elif image_url:
            product.image_url = image_url
        if not image_url and (is_new or not product.image_data):
            label = str(row.get("label") or row.get("character") or "").strip() or name.split()[0]
            product.image_data = make_artwork(name, _palette(name), label=label, category=product.category)
            product.image_mime = "image/jpeg"
            product.image_url = None

        db.session.commit()
        result["created" if is_new else "updated"] += 1
        log(f"{'+' if is_new else '~'} {name}  ${price}  stock {stock}")
    return result


def import_file(path, **kwargs):
    return import_rows(load_rows(path), **kwargs)
