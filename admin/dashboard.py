from datetime import timedelta
from decimal import Decimal

from flask import render_template, url_for
from sqlalchemy import func

from extensions import db
from helper.security import admin_required
from models import Order, Product, utcnow

from . import LOW_STOCK, bp


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

    return render_template("admin/page/dashboard/dashboard.html", paid_count=paid_count, revenue=revenue,
                           today_revenue=totals[days[-1]], pending_count=pending_count,
                           active_count=active_count, low_count=low_count, week=week,
                           week_total=sum(totals.values()), recent=recent, low_stock=low_stock,
                           events=events, now=now)
