from flask import abort, render_template, request
from sqlalchemy import func

from extensions import db
from helper.security import admin_required
from models import Order

from . import bp


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
    count = lambda cond=None: db.session.scalar(
        db.select(func.count(Order.id)).where(cond) if cond is not None else db.select(func.count(Order.id)))
    counts = {"ALL": count(), "PAID": count(Order.status == Order.STATUS_PAID),
              "PENDING": count(Order.status == Order.STATUS_PENDING)}
    revenue = db.session.scalar(db.select(func.coalesce(func.sum(Order.total_amount), 0))
                                .where(Order.status == Order.STATUS_PAID))
    return render_template("admin/page/orders/orders.html", orders=db.session.scalars(stmt).all(), status=status,
                           q=q, counts=counts, revenue=revenue)


@bp.get("/orders/<int:order_id>")
@admin_required
def order_detail(order_id):
    order = db.session.get(Order, order_id) or abort(404)
    return render_template("admin/page/orders/order_detail.html", order=order)
