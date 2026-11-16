from decimal import Decimal, InvalidOperation

from flask import abort, flash, redirect, render_template, request, url_for
from sqlalchemy import func

from extensions import db
from helper.images import ImageError, process_upload
from helper.security import admin_required
from models import OrderItem, Product

from . import LOW_STOCK, bp


PRODUCT_FILTERS = {
    "all": ("All", None),
    "low": ("Low stock", lambda: db.and_(Product.is_active.is_(True), Product.stock <= LOW_STOCK)),
    "soldout": ("Sold out", lambda: Product.stock == 0),
    "hidden": ("Hidden", lambda: Product.is_active.is_(False)),
}


@bp.get("/products")
@admin_required
def products():
    key = request.args.get("filter", "all")
    if key not in PRODUCT_FILTERS:
        key = "all"
    q = request.args.get("q", "").strip()
    counts = {k: db.session.scalar(db.select(func.count(Product.id)).where(cond()) if cond else
                                   db.select(func.count(Product.id)))
              for k, (_, cond) in PRODUCT_FILTERS.items()}
    stmt = db.select(Product).order_by(Product.id.desc())
    if PRODUCT_FILTERS[key][1]:
        stmt = stmt.where(PRODUCT_FILTERS[key][1]())
    if q:
        like = f"%{q}%"
        stmt = stmt.where(db.or_(Product.name.ilike(like), Product.category.ilike(like)))
    active = db.session.scalar(db.select(func.count(Product.id)).where(Product.is_active.is_(True)))
    return render_template("admin/page/products/products.html", products=db.session.scalars(stmt).all(),
                           filters=PRODUCT_FILTERS, counts=counts, filter=key, q=q, active_count=active)


def _back_to_products():
    nxt = request.form.get("next", "")
    return redirect(nxt if nxt.startswith("/admin/") else url_for("admin.products"))


@bp.post("/products/<int:product_id>/restock")
@admin_required
def product_restock(product_id):
    product = db.session.get(Product, product_id) or abort(404)
    product.stock += 5
    db.session.commit()
    flash(f"{product.name} restocked: {product.stock} in stock.", "success")
    return _back_to_products()


@bp.post("/products/<int:product_id>/toggle")
@admin_required
def product_toggle(product_id):
    product = db.session.get(Product, product_id) or abort(404)
    product.is_active = not product.is_active
    db.session.commit()
    flash(f"{product.name} is {'back in the shop' if product.is_active else 'hidden from the shop'}.", "success")
    return _back_to_products()


def _parse_product_form(product):
    f = request.form
    data = {
        "name": f.get("name", "").strip(),
        "category": f.get("category", "").strip()[:40],
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
        product.category = data["category"] or None
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
    return render_template("admin/page/products/product_form.html", product=None, data=data, errors=errors,
                           categories=_categories())


@bp.route("/products/<int:product_id>/edit", methods=["GET", "POST"])
@admin_required
def product_edit(product_id):
    product = db.session.get(Product, product_id) or abort(404)
    data = {"name": product.name, "category": product.category, "description": product.description, "price": f"{product.price:.2f}",
            "stock": product.stock, "is_active": product.is_active, "image_url": product.image_url or ""}
    errors = {}
    if request.method == "POST":
        data, errors = _parse_product_form(product)
        if not errors:
            db.session.commit()
            flash(f"Product “{product.name}” updated.", "success")
            return redirect(url_for("admin.products"))
        db.session.rollback()
    return render_template("admin/page/products/product_form.html", product=product, data=data, errors=errors,
                           categories=_categories())


def _categories():
    return db.session.scalars(db.select(Product.category).where(Product.category.is_not(None))
                              .distinct().order_by(Product.category)).all()


@bp.post("/products/<int:product_id>/delete")
@admin_required
def product_delete(product_id):
    product = db.session.get(Product, product_id) or abort(404)
    db.session.execute(db.update(OrderItem).where(OrderItem.product_id == product.id)
                       .values(product_id=None))
    db.session.delete(product)
    db.session.commit()
    flash(f"Product “{product.name}” deleted.", "success")
    return redirect(url_for("admin.products"))
