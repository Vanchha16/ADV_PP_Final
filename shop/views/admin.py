from decimal import Decimal, InvalidOperation

from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   session, url_for)
from sqlalchemy import func

from ..extensions import db
from ..images import ImageError, process_upload
from ..models import Order, OrderItem, Product
from ..security import admin_required, check_admin_credentials

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("is_admin"):
        return redirect(url_for("admin.products"))
    if request.method == "POST":
        if check_admin_credentials(request.form.get("username", ""), request.form.get("password", "")):
            session["is_admin"] = True
            flash("Welcome back!", "success")
            nxt = request.args.get("next", "")
            if nxt.startswith("/admin") and not nxt.startswith("//"):
                return redirect(nxt)
            return redirect(url_for("admin.products"))
        flash("Invalid username or password.", "danger")
    return render_template("admin/login.html")


@bp.post("/logout")
def logout():
    session.pop("is_admin", None)
    flash("You have been logged out.", "info")
    return redirect(url_for("admin.login"))


@bp.get("/")
@admin_required
def home():
    return redirect(url_for("admin.products"))


# ----------------------------------------------------------------- products

@bp.get("/products")
@admin_required
def products():
    items = db.session.scalars(db.select(Product).order_by(Product.id.desc())).all()
    return render_template("admin/products.html", products=items)


def _parse_product_form(product):
    f = request.form
    data = {
        "name": f.get("name", "").strip(),
        "description": f.get("description", "").strip(),
        "price": f.get("price", "").strip(),
        "stock": f.get("stock", "").strip(),
        "is_active": f.get("status", "active") == "active",
        "image_url": f.get("image_url", "").strip(),
    }
    errors = {}
    if not 1 <= len(data["name"]) <= 120:
        errors["name"] = "Name is required (max 120 characters)."
    try:
        price = Decimal(data["price"]).quantize(Decimal("0.01"))
        if price <= 0 or price > Decimal("99999999"):
            raise InvalidOperation
    except InvalidOperation:
        errors["price"] = "Enter a price greater than 0."
        price = None
    try:
        stock = int(data["stock"])
        if stock < 0:
            raise ValueError
    except ValueError:
        errors["stock"] = "Stock must be a whole number ≥ 0."
        stock = None
    if data["image_url"] and not data["image_url"].startswith(("http://", "https://")):
        errors["image_url"] = "Image URL must start with http:// or https://"

    upload = request.files.get("image")
    image = None
    if upload and upload.filename:
        try:
            image = process_upload(upload)
        except ImageError as exc:
            errors["image"] = str(exc)

    if not errors:
        product.name = data["name"]
        product.description = data["description"]
        product.price = price
        product.stock = stock
        product.is_active = data["is_active"]
        product.image_url = data["image_url"] or None
        if image:
            product.image_data, product.image_mime = image
        elif f.get("remove_image"):
            product.image_data = product.image_mime = None
    return data, errors


@bp.route("/products/new", methods=["GET", "POST"])
@admin_required
def product_new():
    product = Product()
    data, errors = {"is_active": True}, {}
    if request.method == "POST":
        data, errors = _parse_product_form(product)
        if not errors:
            db.session.add(product)
            db.session.commit()
            flash(f"Product “{product.name}” created.", "success")
            return redirect(url_for("admin.products"))
    return render_template("admin/product_form.html", product=None, data=data, errors=errors)


@bp.route("/products/<int:product_id>/edit", methods=["GET", "POST"])
@admin_required
def product_edit(product_id):
    product = db.session.get(Product, product_id) or abort(404)
    data = {"name": product.name, "description": product.description, "price": f"{product.price:.2f}",
            "stock": product.stock, "is_active": product.is_active, "image_url": product.image_url or ""}
    errors = {}
    if request.method == "POST":
        data, errors = _parse_product_form(product)
        if not errors:
            db.session.commit()
            flash(f"Product “{product.name}” updated.", "success")
            return redirect(url_for("admin.products"))
        db.session.rollback()
    return render_template("admin/product_form.html", product=product, data=data, errors=errors)


@bp.post("/products/<int:product_id>/delete")
@admin_required
def product_delete(product_id):
    product = db.session.get(Product, product_id) or abort(404)
    # Keep order history intact: detach line items (they keep name & price).
    db.session.execute(db.update(OrderItem).where(OrderItem.product_id == product.id)
                       .values(product_id=None))
    db.session.delete(product)
    db.session.commit()
    flash(f"Product “{product.name}” deleted.", "success")
    return redirect(url_for("admin.products"))


# ------------------------------------------------------------------- orders

@bp.get("/orders")
@admin_required
def orders():
    status = request.args.get("status", "PAID").upper()
    stmt = db.select(Order).order_by(Order.created_at.desc())
    if status in (Order.STATUS_PAID, Order.STATUS_PENDING):
        stmt = stmt.where(Order.status == status)
    else:
        status = "ALL"
    items = db.session.scalars(stmt).all()
    stats = db.session.execute(
        db.select(func.count(Order.id), func.coalesce(func.sum(Order.total_amount), 0))
        .where(Order.status == Order.STATUS_PAID)).one()
    pending = db.session.scalar(db.select(func.count(Order.id)).where(Order.status == Order.STATUS_PENDING))
    return render_template("admin/orders.html", orders=items, status=status,
                           paid_count=stats[0], revenue=stats[1], pending_count=pending)


@bp.get("/orders/<int:order_id>")
@admin_required
def order_detail(order_id):
    order = db.session.get(Order, order_id) or abort(404)
    return render_template("admin/order_detail.html", order=order)
