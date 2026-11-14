from datetime import timedelta
from decimal import Decimal, InvalidOperation

from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   session, url_for)
from sqlalchemy import func

from ..extensions import db
from ..images import ImageError, process_upload
from ..models import Order, OrderItem, Product, utcnow
from ..security import admin_required, check_admin_credentials

bp = Blueprint("admin", __name__, url_prefix="/admin")

LOW_STOCK = 3  # "low stock" = 3 or fewer left


@bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("is_admin"):
        return redirect(url_for("admin.dashboard"))
    if request.method == "POST":
        if check_admin_credentials(request.form.get("username", ""), request.form.get("password", "")):
            session["is_admin"] = True
            flash("Welcome back!", "success")
            nxt = request.args.get("next", "")
            if nxt.startswith("/admin") and not nxt.startswith("//"):
                return redirect(nxt)
            return redirect(url_for("admin.dashboard"))
        flash("Invalid username or password.", "danger")
    return render_template("admin/login.html")


@bp.post("/logout")
def logout():
    session.pop("is_admin", None)
    flash("You have been logged out.", "info")
    return redirect(url_for("admin.login"))


@bp.app_context_processor
def admin_globals():
    if not session.get("is_admin") or not request.blueprint == "admin":
        return {}
    pending = db.session.scalar(db.select(func.count(Order.id)).where(Order.status == Order.STATUS_PENDING))
    return {"sidebar_pending": pending}


@bp.get("/")
@admin_required
def dashboard():
    paid = Order.status == Order.STATUS_PAID
    paid_count, revenue = db.session.execute(
        db.select(func.count(Order.id), func.coalesce(func.sum(Order.total_amount), 0)).where(paid)).one()
    pending_count = db.session.scalar(db.select(func.count(Order.id)).where(Order.status == Order.STATUS_PENDING))
    active_count = db.session.scalar(db.select(func.count(Product.id)).where(Product.is_active.is_(True)))
    low_count = db.session.scalar(db.select(func.count(Product.id))
                                  .where(Product.is_active.is_(True), Product.stock <= LOW_STOCK))

    # Revenue per day for the last 7 days (grouped in Python so it works on SQLite and Postgres).
    now = utcnow()
    days = [now.date() - timedelta(days=i) for i in range(6, -1, -1)]
    totals = {d: Decimal("0") for d in days}
    for paid_at, amount in db.session.execute(
            db.select(Order.paid_at, Order.total_amount).where(paid, Order.paid_at >= now - timedelta(days=7))):
        if paid_at and paid_at.date() in totals:
            totals[paid_at.date()] += Decimal(amount)
    peak = max(totals.values()) or Decimal("1")
    week = [{"label": d.strftime("%a"), "date": d.strftime("%d %b"), "total": totals[d],
             "pct": int(totals[d] / peak * 100)} for d in days]

    recent = db.session.scalars(db.select(Order).order_by(Order.created_at.desc()).limit(6)).all()
    low_stock = db.session.scalars(
        db.select(Product).where(Product.is_active.is_(True), Product.stock <= LOW_STOCK)
        .order_by(Product.stock, Product.name).limit(6)).all()

    # "Live activity": newest payments and orders, plus products that sold out.
    events = []
    for o in db.session.scalars(db.select(Order).order_by(Order.created_at.desc()).limit(8)):
        if o.is_paid:
            events.append({"kind": "paid", "at": o.paid_at or o.created_at, "title": f"{o.number} paid",
                           "text": f"{o.customer_name} paid {o.total_amount:,.2f} {o.currency} with KHQR",
                           "url": url_for("admin.order_detail", order_id=o.id)})
        events.append({"kind": "order", "at": o.created_at, "title": f"New order {o.number}",
                       "text": f"{o.customer_name}, {o.item_count} item{'s' if o.item_count != 1 else ''}",
                       "url": url_for("admin.order_detail", order_id=o.id)})
    for p in db.session.scalars(db.select(Product).where(Product.is_active.is_(True), Product.stock == 0)
                                .order_by(Product.updated_at.desc()).limit(3)):
        events.append({"kind": "sold_out", "at": p.updated_at, "title": "Sold out", "text": p.name,
                       "url": url_for("admin.product_edit", product_id=p.id), "product": p})
    events = sorted(events, key=lambda e: e["at"], reverse=True)[:7]

    return render_template("admin/dashboard.html", paid_count=paid_count, revenue=revenue,
                           today_revenue=totals[days[-1]], pending_count=pending_count,
                           active_count=active_count, low_count=low_count, week=week,
                           week_total=sum(totals.values()), recent=recent, low_stock=low_stock,
                           events=events, now=now)


# ----------------------------------------------------------------- products

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
    return render_template("admin/products.html", products=db.session.scalars(stmt).all(),
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
    return render_template("admin/product_form.html", product=None, data=data, errors=errors,
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
    return render_template("admin/product_form.html", product=product, data=data, errors=errors,
                           categories=_categories())


def _categories():
    return db.session.scalars(db.select(Product.category).where(Product.category.is_not(None))
                              .distinct().order_by(Product.category)).all()


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
    status = request.args.get("status", "ALL").upper()
    if status not in (Order.STATUS_PAID, Order.STATUS_PENDING):
        status = "ALL"
    q = request.args.get("q", "").strip()
    stmt = db.select(Order).order_by(Order.created_at.desc())
    if status != "ALL":
        stmt = stmt.where(Order.status == status)
    if q:
        like = f"%{q}%"
        conds = [Order.customer_name.ilike(like), Order.phone.ilike(like), Order.email.ilike(like)]
        digits = q.lstrip("#").lstrip("0")
        if digits.isdigit():
            conds.append(Order.id == int(digits))
        stmt = stmt.where(db.or_(*conds))
    count = lambda cond=None: db.session.scalar(  # noqa: E731
        db.select(func.count(Order.id)).where(cond) if cond is not None else db.select(func.count(Order.id)))
    counts = {"ALL": count(), "PAID": count(Order.status == Order.STATUS_PAID),
              "PENDING": count(Order.status == Order.STATUS_PENDING)}
    revenue = db.session.scalar(db.select(func.coalesce(func.sum(Order.total_amount), 0))
                                .where(Order.status == Order.STATUS_PAID))
    return render_template("admin/orders.html", orders=db.session.scalars(stmt).all(), status=status,
                           q=q, counts=counts, revenue=revenue)


@bp.get("/orders/<int:order_id>")
@admin_required
def order_detail(order_id):
    order = db.session.get(Order, order_id) or abort(404)
    return render_template("admin/order_detail.html", order=order)
