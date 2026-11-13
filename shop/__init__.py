import logging
import os
from decimal import Decimal

import click
from flask import Flask, render_template
from sqlalchemy.exc import OperationalError
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import Config
from .extensions import db


def create_app(config_overrides=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(Config)
    if config_overrides:
        app.config.update(config_overrides)
    os.makedirs(app.instance_path, exist_ok=True)
    if not app.config.get("SQLALCHEMY_DATABASE_URI"):
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(app.instance_path, "shop.db")

    # Trust X-Forwarded-* from the hosting platform's proxy so external URLs
    # (share links, og:image) use the public https host.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    logging.basicConfig(level=logging.INFO)

    db.init_app(app)

    from . import cart, security
    from .views.admin import bp as admin_bp
    from .views.public import bp as public_bp

    app.register_blueprint(public_bp)
    app.register_blueprint(admin_bp)

    app.before_request(security.verify_csrf)

    @app.template_filter("money")
    def money(value, currency="USD"):
        value = Decimal(value or 0)
        if currency == "KHR":
            return f"៛{value:,.0f}"
        return f"${value:,.2f}"

    @app.template_filter("dt")
    def dt(value):
        return value.strftime("%d %b %Y, %H:%M") if value else "—"

    @app.context_processor
    def inject_globals():
        return {
            "shop_name": app.config["SHOP_NAME"],
            "csrf_token": security.csrf_token,
            "cart_count": cart.count(),
        }

    for code in (400, 404, 413, 500):
        app.register_error_handler(code, lambda e, code=code: (
            render_template("errors/error.html", error=e, code=code), code))

    with app.app_context():
        try:
            db.create_all()
        except OperationalError:  # another worker created the tables first
            db.session.rollback()
        if app.config["AUTO_SEED"]:
            from .seed import seed_if_empty
            seed_if_empty()

    @app.cli.command("seed")
    @click.option("--reset", is_flag=True, help="Drop all data first.")
    def seed_command(reset):
        """Load sample products."""
        from .seed import seed_products
        if reset:
            db.drop_all()
            db.create_all()
        n = seed_products()
        click.echo(f"Seeded {n} products.")

    return app
