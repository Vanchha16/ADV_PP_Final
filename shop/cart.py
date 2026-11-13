"""Session-backed shopping cart: {"<product_id>": quantity}."""
from dataclasses import dataclass
from decimal import Decimal

from flask import session

from .extensions import db
from .models import Product

SESSION_KEY = "cart"


@dataclass
class CartLine:
    product: Product
    quantity: int

    @property
    def subtotal(self):
        return (Decimal(self.product.price) * self.quantity).quantize(Decimal("0.01"))

    @property
    def over_stock(self):
        return self.quantity > self.product.stock


def _raw():
    return dict(session.get(SESSION_KEY, {}))


def _save(data):
    session[SESSION_KEY] = data
    session.modified = True


def count():
    return sum(_raw().values())


def quantity_of(product_id):
    return _raw().get(str(product_id), 0)


def add(product_id, qty):
    data = _raw()
    key = str(product_id)
    data[key] = data.get(key, 0) + qty
    _save(data)


def set_quantity(product_id, qty):
    data = _raw()
    key = str(product_id)
    if qty <= 0:
        data.pop(key, None)
    else:
        data[key] = qty
    _save(data)


def remove(product_id):
    set_quantity(product_id, 0)


def clear():
    session.pop(SESSION_KEY, None)


def lines():
    """Cart lines for products that still exist and are active.

    Items whose product was deleted or deactivated are silently dropped.
    """
    data = _raw()
    if not data:
        return []
    ids = [int(k) for k in data]
    products = {p.id: p for p in db.session.scalars(
        db.select(Product).where(Product.id.in_(ids), Product.is_active.is_(True)))}
    result, cleaned = [], {}
    for key, qty in data.items():
        product = products.get(int(key))
        if product and qty > 0:
            result.append(CartLine(product, qty))
            cleaned[key] = qty
    if cleaned != data:
        _save(cleaned)
    return result


def total(cart_lines):
    return sum((l.subtotal for l in cart_lines), Decimal("0.00"))
