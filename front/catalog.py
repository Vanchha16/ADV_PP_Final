from decimal import Decimal, InvalidOperation

from flask import Blueprint, Response, abort, render_template, request, url_for
from sqlalchemy import func, or_

from extensions import db
from helper import cart
from helper.common import active_product_or_404
from models import Product

bp = Blueprint("catalog", __name__)


SORTS = {
    "new": ("Newest", (Product.created_at.desc(), Product.id.desc())),
    "price_asc": ("Price: low to high", (Product.price.asc(), Product.id.desc())),
    "price_desc": ("Price: high to low", (Product.price.desc(), Product.id.desc())),
    "name": ("Name: A to Z", (Product.name.asc(),)),
}


BRANDS = [
    ("Jordan", "Air Jordan"), ("Nike", "Nike"), ("adidas", "adidas"), ("New Balance", "New Balance"),
    ("ASICS", "ASICS"), ("HOKA", "HOKA"), ("Salomon", "Salomon"), ("Converse", "Converse"),
    ("Onitsuka Tiger", "Onitsuka Tiger"), ("Vans", "Vans"),
]
BRAND_PREFIX = dict(BRANDS)
FILTER_ARGS = ("q", "category", "brand", "in_stock", "min", "max", "sort")


def brand_of(name):
    for brand, prefix in BRANDS:
        if name.lower().startswith(prefix.lower()):
            return brand
    return None


def _shop_url(**changes):
    args = {k: v for k, v in request.args.items() if k in FILTER_ARGS and v}
    for key, value in changes.items():
        if value in (None, ""):
            args.pop(key, None)
        else:
            args[key] = value
    if args.get("sort") == "new":
        args.pop("sort")
    return url_for("catalog.index", **args) + "#products"


def _home_picks(products):
    in_stock = sorted((p for p in products if p.in_stock), key=lambda p: (-p.price, p.id))
    featured, seen = [], set()
    for p in in_stock:
        if p.category and p.category not in seen:
            featured.append(p)
            seen.add(p.category)
    deal = next((p for p in in_stock if p.price <= 100 and p not in featured), None)
    if deal:
        featured.append(deal)
    tiles = {}
    for p in in_stock:
        if p.category and p.category not in tiles and p not in featured:
            tiles[p.category] = p
    return featured[:4], tiles


def _money_arg(name):
    try:
        value = Decimal(request.args.get(name, "").strip())
        return value if value >= 0 else None
    except (InvalidOperation, ValueError):
        return None


@bp.get("/")
def index():
    q = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    brand = request.args.get("brand", "").strip()
    if brand not in BRAND_PREFIX:
        brand = ""
    in_stock_only = request.args.get("in_stock") == "1"
    min_price, max_price = _money_arg("min"), _money_arg("max")
    sort = request.args.get("sort", "new")
    if sort not in SORTS:
        sort = "new"

    active = Product.is_active.is_(True)
    counts = dict(db.session.execute(
        db.select(Product.category, func.count(Product.id))
        .where(active, Product.category.is_not(None))
        .group_by(Product.category).order_by(Product.category)).all())
    total_active = db.session.scalar(db.select(func.count(Product.id)).where(active))
    if category not in counts:
        category = ""

    stmt = db.select(Product).where(active)
    if category:
        stmt = stmt.where(Product.category == category)
    if brand:
        stmt = stmt.where(Product.name.ilike(BRAND_PREFIX[brand] + "%"))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Product.name.ilike(like), Product.description.ilike(like),
                              Product.category.ilike(like)))
    if in_stock_only:
        stmt = stmt.where(Product.stock > 0)
    if min_price is not None:
        stmt = stmt.where(Product.price >= min_price)
    if max_price is not None:
        stmt = stmt.where(Product.price <= max_price)
    products = db.session.scalars(stmt.order_by(*SORTS[sort][1])).all()

    filtered = bool(q or category or brand or in_stock_only or min_price is not None or max_price is not None)
    featured, tiles = _home_picks(products) if not filtered else ([], {})
    return render_template("front/page/home/index.html", products=products, q=q, category=category, brand=brand,
                           categories=counts, total_active=total_active, in_stock_only=in_stock_only,
                           min_price=min_price, max_price=max_price, sort=sort, sorts=SORTS,
                           filtered=filtered, featured=featured, tiles=tiles,
                           brand_of=brand_of, shop_url=_shop_url)


@bp.get("/product/<int:product_id>")
def product_detail(product_id):
    product = active_product_or_404(product_id)
    share_url = url_for("catalog.product_detail", product_id=product.id, _external=True)
    in_cart = cart.quantity_of(product.id)
    return render_template("front/page/product/product.html", product=product, share_url=share_url,
                           max_qty=max(0, product.stock - in_cart), in_cart=in_cart)


@bp.get("/product/<int:product_id>/image")
def product_image(product_id):
    product = db.session.get(Product, product_id)
    if not product or not product.image_data:
        abort(404)
    resp = Response(product.image_data, mimetype=product.image_mime or "image/jpeg")
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp
