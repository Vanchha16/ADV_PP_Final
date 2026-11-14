import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from flask import (Blueprint, Response, abort, current_app, flash, jsonify,
                   redirect, render_template, request, session, url_for)
from sqlalchemy import func, or_

from .. import cart, payments
from ..extensions import db
from ..models import Order, OrderItem, Product

bp = Blueprint("public", __name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^\+?[0-9 ()-]{8,20}$")


def _active_product_or_404(product_id):
    product = db.session.get(Product, product_id)
    if not product or not product.is_active:
        abort(404)
    return product


def _int(value, default=1):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_next(default):
    nxt = request.form.get("next") or request.args.get("next") or ""
    # Only allow relative paths on this site (prevents open redirects).
    return nxt if nxt.startswith("/") and not nxt.startswith("//") else default


# ---------------------------------------------------------------- catalogue

SORTS = {
    "new": ("Newest", (Product.created_at.desc(), Product.id.desc())),
    "price_asc": ("Price: low to high", (Product.price.asc(), Product.id.desc())),
    "price_desc": ("Price: high to low", (Product.price.desc(), Product.id.desc())),
    "name": ("Name: A to Z", (Product.name.asc(),)),
}


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

    filtered = bool(q or category or in_stock_only or min_price is not None or max_price is not None)
    return render_template("shop/index.html", products=products, q=q, category=category,
                           categories=counts, total_active=total_active, in_stock_only=in_stock_only,
                           min_price=min_price, max_price=max_price, sort=sort, sorts=SORTS,
                           filtered=filtered)


@bp.get("/product/<int:product_id>")
def product_detail(product_id):
    product = _active_product_or_404(product_id)
    share_url = url_for("public.product_detail", product_id=product.id, _external=True)
    in_cart = cart.quantity_of(product.id)
    return render_template("shop/product.html", product=product, share_url=share_url,
                           max_qty=max(0, product.stock - in_cart), in_cart=in_cart)


@bp.get("/product/<int:product_id>/image")
def product_image(product_id):
    product = db.session.get(Product, product_id)
    if not product or not product.image_data:
        abort(404)
    resp = Response(product.image_data, mimetype=product.image_mime or "image/jpeg")
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


# --------------------------------------------------------------------- cart

@bp.post("/cart/add")
def cart_add():
    product = _active_product_or_404(_int(request.form.get("product_id"), 0))
    qty = max(1, _int(request.form.get("quantity"), 1))
    available = product.stock - cart.quantity_of(product.id)
    if available <= 0:
        flash(f"Sorry, no more “{product.name}” in stock.", "warning")
    else:
        if qty > available:
            flash(f"Only {available} more available; added {available}.", "warning")
            qty = available
        cart.add(product.id, qty)
        flash(f"Added {qty} × {product.name} to your cart.", "success")
    return redirect(_safe_next(url_for("public.view_cart")))


@bp.get("/cart")
def view_cart():
    lines = cart.lines()
    return render_template("shop/cart.html", lines=lines, total=cart.total(lines))


@bp.post("/cart/update")
def cart_update():
    for line in cart.lines():
        raw = request.form.get(f"qty_{line.product.id}")
        if raw is None:
            continue
        qty = max(0, _int(raw, line.quantity))
        if qty > line.product.stock:
            flash(f"Only {line.product.stock} “{line.product.name}” in stock.", "warning")
            qty = line.product.stock
        cart.set_quantity(line.product.id, qty)
    flash("Cart updated.", "success")
    return redirect(url_for("public.view_cart"))


@bp.post("/cart/remove/<int:product_id>")
def cart_remove(product_id):
    cart.remove(product_id)
    flash("Item removed from cart.", "info")
    return redirect(url_for("public.view_cart"))


# ----------------------------------------------------------------- checkout

@bp.route("/checkout", methods=["GET", "POST"])
def checkout():
    lines = cart.lines()
    if not lines:
        flash("Your cart is empty.", "info")
        return redirect(url_for("public.index"))
    total = cart.total(lines)
    form = {k: request.form.get(k, "").strip()
            for k in ("customer_name", "email", "phone", "shipping_address")}
    errors = {}

    if request.method == "POST":
        if not 2 <= len(form["customer_name"]) <= 120:
            errors["customer_name"] = "Please enter your full name."
        if not EMAIL_RE.match(form["email"]) or len(form["email"]) > 200:
            errors["email"] = "Please enter a valid email address."
        if not PHONE_RE.match(form["phone"]):
            errors["phone"] = "Please enter a valid phone number (e.g. 012 345 678)."
        if not 5 <= len(form["shipping_address"]) <= 1000:
            errors["shipping_address"] = "Please enter your shipping address."
        short = [l for l in lines if l.over_stock]
        if short:
            for l in short:
                flash(f"Only {l.product.stock} “{l.product.name}” left. Please update your cart.", "danger")
            return redirect(url_for("public.view_cart"))

        if not errors:
            order = Order(**form, total_amount=total,
                          currency=current_app.config["KHQR_CURRENCY"])
            for l in lines:
                order.items.append(OrderItem(product_id=l.product.id, product_name=l.product.name,
                                             unit_price=l.product.price, quantity=l.quantity))
            db.session.add(order)
            db.session.flush()  # assigns order.id for the bill number
            payments.assign_new_qr(order)
            db.session.commit()
            session["pending_order"] = order.public_id
            return redirect(url_for("public.pay", public_id=order.public_id))

    return render_template("shop/checkout.html", lines=lines, total=total, form=form, errors=errors)


def _order_or_404(public_id):
    order = db.session.scalar(db.select(Order).where(Order.public_id == public_id))
    if not order:
        abort(404)
    return order


@bp.get("/order/<public_id>/pay")
def pay(public_id):
    order = _order_or_404(public_id)
    if order.is_paid:
        return redirect(url_for("public.confirmation", public_id=public_id))
    return render_template("shop/pay.html", order=order,
                           qr_image=payments.qr_data_uri(order.khqr_string),
                           demo_mode=payments.demo_mode())


@bp.get("/order/<public_id>/status")
def order_status(public_id):
    order = _order_or_404(public_id)
    try:
        status = payments.refresh_status(order)
    except payments.BakongAuthError:
        current_app.logger.error("Bakong token rejected; renew BAKONG_TOKEN.")
        status = order.status
    body = {"status": status, "expired": order.qr_expired, "seconds_left": order.seconds_left}
    if status == Order.STATUS_PAID:
        body["redirect"] = url_for("public.confirmation", public_id=public_id)
    return jsonify(body)


@bp.post("/order/<public_id>/regenerate")
def regenerate_qr(public_id):
    order = _order_or_404(public_id)
    if order.status == Order.STATUS_PENDING:
        payments.refresh_status(order)  # don't replace a QR that was just paid
    if order.status == Order.STATUS_PENDING:
        payments.assign_new_qr(order)
        db.session.commit()
        flash("A new KHQR code has been generated.", "info")
    return redirect(url_for("public.pay", public_id=public_id))


@bp.post("/order/<public_id>/simulate-payment")
def simulate_payment(public_id):
    if not payments.demo_mode():
        abort(404)
    order = _order_or_404(public_id)
    payments.mark_paid(order, {"hash": f"DEMO-{order.khqr_md5[:12]}", "fromAccountId": "demo@bakong"})
    return redirect(url_for("public.confirmation", public_id=public_id))


@bp.get("/order/<public_id>/confirmation")
def confirmation(public_id):
    order = _order_or_404(public_id)
    if not order.is_paid:
        return redirect(url_for("public.pay", public_id=public_id))
    if session.get("pending_order") == public_id:
        cart.clear()
        session.pop("pending_order", None)
    return render_template("shop/confirmation.html", order=order)


@bp.app_context_processor
def inject_year():
    return {"current_year": datetime.now().year}
