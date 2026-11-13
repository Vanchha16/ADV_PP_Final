import re
from decimal import Decimal

from shop.extensions import db
from shop.models import Order, Product

from .conftest import csrf


def crc16_ccitt(data: str) -> str:
    crc = 0xFFFF
    for b in data.encode():
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else crc << 1
            crc &= 0xFFFF
    return f"{crc:04X}"


def first_active(app, min_stock=2):
    with app.app_context():
        p = db.session.scalars(db.select(Product).where(Product.is_active.is_(True),
                                                        Product.stock >= min_stock)).first()
        return p.id, p.price, p.stock


def place_order(client, app, qty=2):
    pid, price, _ = first_active(app)
    token = csrf(client)
    client.post("/cart/add", data={"csrf_token": token, "product_id": pid, "quantity": qty})
    r = client.post("/checkout", data={
        "csrf_token": token, "customer_name": "Sok Dara", "email": "dara@example.com",
        "phone": "012 345 678", "shipping_address": "#12, St 271, Phnom Penh"})
    assert r.status_code == 302 and "/pay" in r.location
    public_id = r.location.split("/order/")[1].split("/")[0]
    return public_id, pid, price


def test_home_lists_only_active_products(client):
    html = client.get("/").get_data(as_text=True)
    assert "Ninja Hero Action Figure" in html
    assert "Limited Collector Figure Box" not in html  # inactive


def test_product_detail_has_share_links(client, app):
    pid, *_ = first_active(app)
    html = client.get(f"/product/{pid}").get_data(as_text=True)
    assert "facebook.com/sharer/sharer.php?u=" in html
    assert "t.me/share/url?url=" in html
    assert 'property="og:image"' in html


def test_inactive_product_is_404(client, app):
    with app.app_context():
        pid = db.session.scalar(db.select(Product.id).where(Product.is_active.is_(False)))
    assert client.get(f"/product/{pid}").status_code == 404


def test_post_without_csrf_rejected(client, app):
    pid, *_ = first_active(app)
    assert client.post("/cart/add", data={"product_id": pid}).status_code == 400


def test_cart_caps_quantity_at_stock(client, app):
    pid, _, stock = first_active(app)
    token = csrf(client)
    client.post("/cart/add", data={"csrf_token": token, "product_id": pid, "quantity": stock + 50})
    with client.session_transaction() as s:
        assert s["cart"][str(pid)] == stock


def test_cart_update_and_remove(client, app):
    pid, price, _ = first_active(app)
    token = csrf(client)
    client.post("/cart/add", data={"csrf_token": token, "product_id": pid, "quantity": 1})
    client.post("/cart/update", data={"csrf_token": token, f"qty_{pid}": 2})
    html = client.get("/cart").get_data(as_text=True)
    assert f"${Decimal(price) * 2:,.2f}" in html
    client.post(f"/cart/remove/{pid}", data={"csrf_token": token})
    assert "Your cart is empty" in client.get("/cart").get_data(as_text=True)


def test_checkout_validation(client, app):
    pid, *_ = first_active(app)
    token = csrf(client)
    client.post("/cart/add", data={"csrf_token": token, "product_id": pid, "quantity": 1})
    r = client.post("/checkout", data={"csrf_token": token, "customer_name": "", "email": "bad",
                                       "phone": "x", "shipping_address": ""})
    assert r.status_code == 200
    assert "valid email" in r.get_data(as_text=True)


def test_full_checkout_and_khqr_payment(client, app):
    public_id, pid, price = place_order(client, app, qty=2)
    with app.app_context():
        order = db.session.scalar(db.select(Order).where(Order.public_id == public_id))
        stock_before = db.session.get(Product, pid).stock
        assert order.status == "PENDING"
        assert order.total_amount == Decimal(price) * 2
        qr = order.khqr_string
        # Valid EMV payload: CRC matches and contains our account + amount
        assert qr.startswith("000201010212")  # dynamic QR
        assert qr[-4:] == crc16_ccitt(qr[:-4])
        assert "test_shop@aclb" in qr
        assert len(order.khqr_md5) == 32

    html = client.get(f"/order/{public_id}/pay").get_data(as_text=True)
    assert "data:image/png;base64," in html
    assert client.get(f"/order/{public_id}/status").get_json()["status"] == "PENDING"
    # Confirmation is not reachable before payment
    assert client.get(f"/order/{public_id}/confirmation").status_code == 302

    token = csrf(client, f"/order/{public_id}/pay")
    client.post(f"/order/{public_id}/simulate-payment", data={"csrf_token": token})
    client.post(f"/order/{public_id}/simulate-payment", data={"csrf_token": token})  # idempotent

    html = client.get(f"/order/{public_id}/confirmation").get_data(as_text=True)
    assert "your order is confirmed" in html and "Sok Dara" in html
    with app.app_context():
        assert db.session.get(Product, pid).stock == stock_before - 2
    assert client.get(f"/order/{public_id}/status").get_json()["status"] == "PAID"
    with client.session_transaction() as s:
        assert not s.get("cart")


def test_admin_requires_login(client):
    assert client.get("/admin/products").status_code == 302
    assert client.get("/admin/orders").status_code == 302


def login(client):
    token = csrf(client, "/admin/login")
    r = client.post("/admin/login", data={"csrf_token": token, "username": "admin", "password": "secret"})
    assert r.status_code == 302
    return token


def test_admin_bad_login(client):
    token = csrf(client, "/admin/login")
    r = client.post("/admin/login", data={"csrf_token": token, "username": "admin", "password": "nope"})
    assert "Invalid username or password" in r.get_data(as_text=True)


def test_admin_product_crud(client, app):
    token = login(client)
    r = client.post("/admin/products/new", data={
        "csrf_token": token, "name": "Test Item", "description": "d", "price": "3.50",
        "stock": "7", "status": "active"})
    assert r.status_code == 302
    with app.app_context():
        p = db.session.scalar(db.select(Product).where(Product.name == "Test Item"))
        pid = p.id
        assert p.price == Decimal("3.50") and p.stock == 7
    assert "Test Item" in client.get("/admin/products").get_data(as_text=True)

    token = csrf(client, f"/admin/products/{pid}/edit")
    client.post(f"/admin/products/{pid}/edit", data={
        "csrf_token": token, "name": "Renamed", "description": "", "price": "4", "stock": "1",
        "status": "inactive"})
    with app.app_context():
        p = db.session.get(Product, pid)
        assert p.name == "Renamed" and not p.is_active

    r = client.post("/admin/products/new", data={"csrf_token": token, "name": "", "price": "-1", "stock": "x"})
    assert r.status_code == 200 and "Enter a price" in r.get_data(as_text=True)

    client.post(f"/admin/products/{pid}/delete", data={"csrf_token": token})
    with app.app_context():
        assert db.session.get(Product, pid) is None


def test_admin_image_upload(client, app):
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGBA", (50, 40), (255, 0, 0, 128)).save(buf, format="PNG")
    buf.seek(0)
    token = login(client)
    client.post("/admin/products/new", data={
        "csrf_token": token, "name": "Pic", "price": "1", "stock": "1", "status": "active",
        "image": (buf, "pic.png")}, content_type="multipart/form-data")
    with app.app_context():
        p = db.session.scalar(db.select(Product).where(Product.name == "Pic"))
        assert p.image_mime == "image/jpeg" and p.image_data
    r = client.get(f"/product/{p.id}/image")
    assert r.status_code == 200 and r.mimetype == "image/jpeg"


def test_admin_orders_and_delete_keeps_history(client, app):
    public_id, pid, _ = place_order(client, app, qty=1)
    token = csrf(client, f"/order/{public_id}/pay")
    client.post(f"/order/{public_id}/simulate-payment", data={"csrf_token": token})
    token = login(client)
    html = client.get("/admin/orders").get_data(as_text=True)
    assert "Sok Dara" in html and "012 345 678" in html
    with app.app_context():
        oid = db.session.scalar(db.select(Order.id).where(Order.public_id == public_id))
    client.post(f"/admin/products/{pid}/delete", data={"csrf_token": token})
    html = client.get(f"/admin/orders/{oid}").get_data(as_text=True)
    assert "#12, St 271" in html and "(deleted)" in html


def test_bakong_payment_verification(app, monkeypatch):
    """With a real token, a matching Bakong response marks the order paid."""
    from shop import payments
    with app.test_request_context():
        app.config.update(PAYMENT_DEMO_MODE=False, BAKONG_TOKEN="tok")
        order = Order(customer_name="A", email="a@b.co", phone="012345678", shipping_address="x",
                      total_amount=Decimal("5.00"), currency="USD")
        db.session.add(order); db.session.flush()
        payments.assign_new_qr(order); db.session.commit()

        monkeypatch.setattr(payments, "check_transaction",
                            lambda md5: (payments.PAID, {"amount": 4.0, "currency": "USD",
                                                         "toAccountId": "test_shop@aclb"}))
        assert payments.refresh_status(order) == "PENDING"  # underpaid -> rejected

        monkeypatch.setattr(payments, "check_transaction",
                            lambda md5: (payments.PAID, {"amount": 5.0, "currency": "USD", "hash": "abc",
                                                         "toAccountId": "test_shop@aclb"}))
        assert payments.refresh_status(order) == "PAID"
        assert order.payment_hash == "abc"
