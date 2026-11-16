import logging
import os
from datetime import datetime
from decimal import Decimal

import click
from flask import Flask, render_template
from markupsafe import Markup, escape
from sqlalchemy.exc import OperationalError
from werkzeug.middleware.proxy_fix import ProxyFix

from config import Config
from extensions import db


def create_app(config_overrides=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(Config)
    if config_overrides:
        app.config.update(config_overrides)
    os.makedirs(app.instance_path, exist_ok=True)
    if not app.config.get("SQLALCHEMY_DATABASE_URI"):
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(app.instance_path, "shop.db")

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    logging.basicConfig(level=logging.INFO)

    db.init_app(app)

    from admin import bp as admin_bp
    from api import bp as api_bp
    from front import register_front
    from helper import cart, security

    register_front(app)
    app.register_blueprint(api_bp)
    app.register_blueprint(admin_bp)

    app.before_request(security.verify_csrf)

    @app.context_processor
    def inject_year():
        return {"current_year": datetime.now().year}

    @app.template_filter("money")
    def money(value, currency="USD"):
        value = Decimal(value or 0)
        if currency == "KHR":
            return f"៛{value:,.0f}"
        return f"${value:,.2f}"

    @app.template_global()
    def icon(name, cls=""):
        return Markup(f'<span class="ms {escape(cls)}" aria-hidden="true">{escape(name)}</span>')

    @app.template_filter("ago")
    def ago(value):
        if not value:
            return ""
        from models import utcnow
        secs = max(0, int((utcnow() - value).total_seconds()))
        for size, unit in ((86400, "d"), (3600, "h"), (60, "m")):
            if secs >= size:
                return f"{secs // size}{unit} ago"
        return "just now"

    @app.template_filter("dt")
    def dt(value):
        return value.strftime("%d %b %Y, %H:%M") if value else "—"

    @app.context_processor
    def inject_globals():
        return {
            "shop_name": app.config["SHOP_NAME"],
            "csrf_token": security.csrf_token,
            "cart_count": cart.count(),
            "nav_categories": _nav_categories(),
        }

    def _nav_categories():
        from models import Product
        try:
            return db.session.scalars(
                db.select(Product.category).where(Product.is_active.is_(True), Product.category.is_not(None))
                .distinct().order_by(Product.category)).all()
        except Exception:
            db.session.rollback()
            return []

    for code in (400, 404, 413, 500):
        app.register_error_handler(code, lambda e, code=code: (
            render_template("error/error.html", error=e, code=code), code))

    with app.app_context():
        try:
            db.create_all()
        except OperationalError:
            db.session.rollback()
        _add_missing_columns()
        if app.config["AUTO_SEED"]:
            from helper.seed import seed_if_empty
            seed_if_empty(download_images=app.config["SEED_DOWNLOAD_IMAGES"])

    @app.cli.command("seed")
    @click.option("--reset", is_flag=True, help="Drop all data first.")
    def seed_command(reset):
        from helper.seed import seed_products
        if reset:
            db.drop_all()
            db.create_all()
        n = seed_products()
        click.echo(f"Seeded {n} products.")

    @app.cli.command("import-products")
    @click.argument("path", default="data/products.json", type=click.Path(exists=True, dir_okay=False))
    @click.option("--replace", is_flag=True, help="Delete existing products first (order history is kept).")
    @click.option("--download-images/--no-download-images", default=True,
                  help="Download image_url pictures into the database (default) or keep them as links.")
    def import_products_command(path, replace, download_images):
        from helper.importer import import_file
        result = import_file(path, replace=replace, download_images=download_images, log=click.echo)
        click.echo(f"Done: {result['created']} created, {result['updated']} updated, "
                   f"{result['deleted']} deleted, {len(result['errors'])} errors.")
        for err in result["errors"]:
            click.echo(f"  ! {err}", err=True)

    return app


def _add_missing_columns():
    from sqlalchemy import inspect, text
    wanted = {"products": {"category": "VARCHAR(40)"}}
    insp = inspect(db.engine)
    for table, cols in wanted.items():
        have = {c["name"] for c in insp.get_columns(table)}
        for name, ddl in cols.items():
            if name not in have:
                try:
                    db.session.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                    db.session.commit()
                except Exception:
                    db.session.rollback()


if __name__ == "__main__":
    create_app().run(debug=True)
