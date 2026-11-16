from flask import Blueprint, flash, redirect, render_template, request, url_for

from helper import cart
from helper.common import active_product_or_404, safe_next, to_int

bp = Blueprint("cart", __name__)


@bp.post("/cart/add")
def add():
    product = active_product_or_404(to_int(request.form.get("product_id"), 0))
    qty = max(1, to_int(request.form.get("quantity"), 1))
    available = product.stock - cart.quantity_of(product.id)
    if available <= 0:
        flash(f"Sorry, no more “{product.name}” in stock.", "warning")
    else:
        if qty > available:
            flash(f"Only {available} more available; added {available}.", "warning")
            qty = available
        cart.add(product.id, qty)
        flash(f"Added {qty} × {product.name} to your cart.", "success")
    return redirect(safe_next(url_for("cart.view")))


@bp.get("/cart")
def view():
    lines = cart.lines()
    return render_template("front/page/cart/cart.html", lines=lines, total=cart.total(lines))


@bp.post("/cart/update")
def update():
    for line in cart.lines():
        raw = request.form.get(f"qty_{line.product.id}")
        if raw is None:
            continue
        qty = max(0, to_int(raw, line.quantity))
        if qty > line.product.stock:
            flash(f"Only {line.product.stock} “{line.product.name}” in stock.", "warning")
            qty = line.product.stock
        cart.set_quantity(line.product.id, qty)
    flash("Cart updated.", "success")
    return redirect(url_for("cart.view"))


@bp.post("/cart/remove/<int:product_id>")
def remove(product_id):
    cart.remove(product_id)
    flash("Item removed from cart.", "info")
    return redirect(url_for("cart.view"))
