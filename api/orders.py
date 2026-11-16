from flask import current_app, jsonify, url_for

from helper import payments
from helper.common import order_or_404
from models import Order

from . import bp


@bp.get("/orders/<public_id>/status")
def order_status(public_id):
    order = order_or_404(public_id)
    try:
        status = payments.refresh_status(order)
    except payments.BakongAuthError:
        current_app.logger.error("Bakong token rejected; renew BAKONG_TOKEN.")
        status = order.status
    body = {"status": status, "expired": order.qr_expired, "seconds_left": order.seconds_left}
    if status == Order.STATUS_PAID:
        body["redirect"] = url_for("checkout.confirmation", public_id=public_id)
    return jsonify(body)
