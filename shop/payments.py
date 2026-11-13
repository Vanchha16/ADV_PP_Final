"""Bakong KHQR: QR generation, payment status checks and order settlement."""
import base64
import io
import logging
from datetime import timedelta
from decimal import Decimal

import qrcode
import requests
from bakong_khqr import KHQR
from flask import current_app
from qrcode.constants import ERROR_CORRECT_M

from .extensions import db
from .models import Order, Product, utcnow

log = logging.getLogger(__name__)

PAID, PENDING, FAILED, ERROR = "PAID", "PENDING", "FAILED", "ERROR"


class BakongAuthError(RuntimeError):
    """Token missing, wrong, or expired (Bakong errorCode 6 / HTTP 401)."""


def demo_mode():
    return bool(current_app.config["PAYMENT_DEMO_MODE"])


def assign_new_qr(order):
    """Generate a fresh dynamic KHQR for the order's exact amount."""
    cfg = current_app.config
    # Bill number must be unique per QR so a regenerated QR gets a new md5.
    order.bill_number = f"ORD{order.id}T{int(utcnow().timestamp()) % 100000}"[:25]
    # No token is passed: QR generation is done locally, offline.
    qr = KHQR().create_qr(
        amount=float(order.total_amount),
        account_id=cfg["BAKONG_ACCOUNT_ID"],
        merchant_name=cfg["BAKONG_MERCHANT_NAME"][:25],
        merchant_city=cfg["BAKONG_MERCHANT_CITY"][:15],
        currency=order.currency,
        store_label=cfg["SHOP_NAME"][:25],
        phone_number=cfg["BAKONG_PHONE"] or None,
        bill_number=order.bill_number,
        terminal_label="Web",
        static=False,
    )
    order.khqr_string = str(qr.qr)
    order.khqr_md5 = qr.md5
    order.qr_expires_at = utcnow() + timedelta(minutes=cfg["QR_TTL_MINUTES"])


def qr_data_uri(qr_string):
    img = qrcode.make(qr_string, error_correction=ERROR_CORRECT_M, box_size=10, border=1)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def check_transaction(md5):
    """Ask Bakong whether the QR identified by md5 has been paid.

    Returns (status, data). Raises BakongAuthError when the token is bad.
    """
    cfg = current_app.config
    if not cfg["BAKONG_TOKEN"]:
        return PENDING, None
    headers = {"Authorization": f"Bearer {cfg['BAKONG_TOKEN']}"}
    if cfg["BAKONG_PROXY_KEY"]:
        headers["X-Proxy-Key"] = cfg["BAKONG_PROXY_KEY"]
    try:
        r = requests.post(f"{cfg['BAKONG_API_URL']}/check_transaction_by_md5",
                          json={"md5": md5}, headers=headers, timeout=12)
    except requests.RequestException as exc:
        log.warning("Bakong check md5=%s failed: %s", md5, exc)
        return ERROR, None
    try:
        data = r.json()
    except ValueError:
        log.warning("Bakong check md5=%s http=%s non-JSON body", md5, r.status_code)
        return ERROR, None

    code, err = data.get("responseCode"), data.get("errorCode")
    log.info("Bakong check md5=%s http=%s responseCode=%s errorCode=%s",
             md5, r.status_code, code, err)
    if code == 0 and data.get("data"):
        return PAID, data["data"]
    if r.status_code == 401 or err == 6:
        raise BakongAuthError("Bakong token unauthorized or expired; renew it.")
    if err == 1:
        return PENDING, None
    if err == 3:
        return FAILED, None
    return ERROR, data


def payment_matches(order, data):
    """Make sure the money went to us, in the right currency, for the full amount."""
    cfg = current_app.config
    try:
        amount = Decimal(str(data.get("amount")))
    except Exception:
        return False
    to_account = (data.get("toAccountId") or "").lower()
    return (
        (data.get("currency") or "").upper() == order.currency
        and amount >= Decimal(order.total_amount)
        and (not to_account or to_account == cfg["BAKONG_ACCOUNT_ID"].lower())
    )


def mark_paid(order, data=None):
    """Settle an order exactly once, even if several polls race each other."""
    updated = db.session.execute(
        db.update(Order)
        .where(Order.id == order.id, Order.status == Order.STATUS_PENDING)
        .values(status=Order.STATUS_PAID, paid_at=utcnow(),
                payment_hash=(data or {}).get("hash"),
                payment_from=(data or {}).get("fromAccountId"))
    ).rowcount
    if updated == 1:
        for item in order.items:
            if item.product_id:
                db.session.execute(
                    db.update(Product)
                    .where(Product.id == item.product_id)
                    .values(stock=db.case((Product.stock >= item.quantity,
                                           Product.stock - item.quantity), else_=0))
                )
    db.session.commit()
    db.session.refresh(order)
    return updated == 1


def refresh_status(order):
    """Poll Bakong for a pending order and settle it if paid. Returns order.status."""
    if order.status != Order.STATUS_PENDING or not order.khqr_md5 or demo_mode():
        return order.status
    status, data = check_transaction(order.khqr_md5)
    if status == PAID:
        if payment_matches(order, data):
            mark_paid(order, data)
        else:
            log.error("Order %s: payment data does not match order: %s", order.id, data)
    return order.status
