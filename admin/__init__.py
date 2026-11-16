from flask import Blueprint

bp = Blueprint("admin", __name__, url_prefix="/admin")

LOW_STOCK = 3

from . import auth, dashboard, orders, products
