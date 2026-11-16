import re

from flask import (Blueprint, abort, current_app, flash, redirect, render_template,
                   request, session, url_for)

from extensions import db
from helper import cart, payments
from helper.common import order_or_404
from models import Order, OrderItem

bp = Blueprint("checkout", __name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^\+?[0-9 ()-]{8,20}$")


@bp.route("/checkout", methods=["GET", "POST"])
def index():
    lines = cart.lines()
    if not lines:
        flash("Your cart is empty.", "info")
        return redirect(url_for("catalog.index"))
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
            return redirect(url_for("cart.view"))

        if not errors:
            order = Order(**form, total_amount=total,
                          currency=current_app.config["KHQR_CURRENCY"])
            for l in lines:
                order.items.append(OrderItem(product_id=l.product.id, product_name=l.product.name,
                                             unit_price=l.product.price, quantity=l.quantity))
            db.session.add(order)
            db.session.flush()
            payments.assign_new_qr(order)
            db.session.commit()
            session["pending_order"] = order.public_id
            return redirect(url_for("checkout.pay", public_id=order.public_id))

    return render_template("front/page/checkout/checkout.html", lines=lines, total=total, form=form, errors=errors)


@bp.get("/order/<public_id>/pay")
def pay(public_id):
    order = order_or_404(public_id)
    if order.is_paid:
        return redirect(url_for("checkout.confirmation", public_id=public_id))
    return render_template("front/page/checkout/pay.html", order=order,
                           qr_image=payments.qr_data_uri(order.khqr_string),
                           demo_mode=payments.demo_mode())


@bp.post("/order/<public_id>/regenerate")
def regenerate_qr(public_id):
    order = order_or_404(public_id)
    if order.status == Order.STATUS_PENDING:
        payments.refresh_status(order)
    if order.status == Order.STATUS_PENDING:
        payments.assign_new_qr(order)
        db.session.commit()
        flash("A new KHQR code has been generated.", "info")
    return redirect(url_for("checkout.pay", public_id=public_id))


@bp.post("/order/<public_id>/simulate-payment")
def simulate_payment(public_id):
    if not payments.demo_mode():
        abort(404)
    order = order_or_404(public_id)
    payments.mark_paid(order, {"hash": f"DEMO-{order.khqr_md5[:12]}", "fromAccountId": "demo@bakong"})
    return redirect(url_for("checkout.confirmation", public_id=public_id))


@bp.get("/order/<public_id>/confirmation")
def confirmation(public_id):
    order = order_or_404(public_id)
    if not order.is_paid:
        return redirect(url_for("checkout.pay", public_id=public_id))
    if session.get("pending_order") == public_id:
        cart.clear()
        session.pop("pending_order", None)
    return render_template("front/page/checkout/confirmation.html", order=order)
