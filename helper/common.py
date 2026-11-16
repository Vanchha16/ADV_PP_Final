from flask import abort, request

from extensions import db
from models import Order, Product


def active_product_or_404(product_id):
    product = db.session.get(Product, product_id)
    if not product or not product.is_active:
        abort(404)
    return product


def to_int(value, default=1):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def safe_next(default):
    nxt = request.form.get("next") or request.args.get("next") or ""
    return nxt if nxt.startswith("/") and not nxt.startswith("//") else default


def order_or_404(public_id):
    order = db.session.scalar(db.select(Order).where(Order.public_id == public_id))
    if not order:
        abort(404)
    return order
