from .cart import bp as cart_bp
from .catalog import bp as catalog_bp
from .checkout import bp as checkout_bp


def register_front(app):
    for bp in (catalog_bp, cart_bp, checkout_bp):
        app.register_blueprint(bp)
