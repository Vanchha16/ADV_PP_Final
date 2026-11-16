from flask import url_for

from extensions import db

from .base import utcnow


class Product(db.Model):
    __tablename__ = "products"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    category = db.Column(db.String(40), nullable=True, index=True)
    description = db.Column(db.Text, nullable=False, default="")
    price = db.Column(db.Numeric(10, 2), nullable=False)
    stock = db.Column(db.Integer, nullable=False, default=0)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    image_data = db.Column(db.LargeBinary, nullable=True)
    image_mime = db.Column(db.String(40), nullable=True)
    image_url = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    @property
    def status_label(self):
        return "Active" if self.is_active else "Inactive"

    @property
    def in_stock(self):
        return self.stock > 0

    @property
    def short_description(self):
        text = (self.description or "").strip()
        return text if len(text) <= 110 else text[:107].rsplit(" ", 1)[0] + "…"

    def image_src(self, external=False):
        if self.image_data:
            return url_for("catalog.product_image", product_id=self.id,
                           v=int(self.updated_at.timestamp()), _external=external)
        if self.image_url:
            return self.image_url
        return url_for("static", filename="img/placeholder.svg", _external=external)
