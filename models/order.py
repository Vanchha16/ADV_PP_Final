import secrets
from decimal import Decimal

from extensions import db

from .base import utcnow


class Order(db.Model):
    __tablename__ = "orders"

    STATUS_PENDING = "PENDING"
    STATUS_PAID = "PAID"
    STATUS_CANCELLED = "CANCELLED"

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(32), unique=True, nullable=False,
                          default=lambda: secrets.token_urlsafe(16))
    customer_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(200), nullable=False)
    phone = db.Column(db.String(40), nullable=False)
    shipping_address = db.Column(db.Text, nullable=False)
    total_amount = db.Column(db.Numeric(10, 2), nullable=False)
    currency = db.Column(db.String(3), nullable=False, default="USD")
    status = db.Column(db.String(12), nullable=False, default=STATUS_PENDING, index=True)

    bill_number = db.Column(db.String(25), nullable=True)
    khqr_string = db.Column(db.Text, nullable=True)
    khqr_md5 = db.Column(db.String(32), nullable=True, index=True)
    qr_expires_at = db.Column(db.DateTime, nullable=True)
    paid_at = db.Column(db.DateTime, nullable=True)
    payment_hash = db.Column(db.String(100), nullable=True)
    payment_from = db.Column(db.String(100), nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)

    items = db.relationship("OrderItem", back_populates="order",
                            cascade="all, delete-orphan", order_by="OrderItem.id")

    @property
    def number(self):
        return f"#{self.id:05d}"

    @property
    def is_paid(self):
        return self.status == self.STATUS_PAID

    @property
    def qr_expired(self):
        return self.qr_expires_at is None or utcnow() >= self.qr_expires_at

    @property
    def seconds_left(self):
        if self.qr_expires_at is None:
            return 0
        return max(0, int((self.qr_expires_at - utcnow()).total_seconds()))

    @property
    def item_count(self):
        return sum(i.quantity for i in self.items)


class OrderItem(db.Model):
    __tablename__ = "order_items"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    product_name = db.Column(db.String(120), nullable=False)
    unit_price = db.Column(db.Numeric(10, 2), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)

    order = db.relationship("Order", back_populates="items")
    product = db.relationship("Product")

    @property
    def subtotal(self):
        return (Decimal(self.unit_price) * self.quantity).quantize(Decimal("0.01"))
