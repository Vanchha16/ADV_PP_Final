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
    assert "Nike Dunk Low Retro White Black Panda" in html
    assert "New Balance 530 White Silver Navy" not in html  # inactive


def test_category_filter(client):
    html = client.get("/?category=Basketball").get_data(as_text=True)
    assert "Air Jordan 4 Retro Military Black" in html
    assert "Vans Old Skool" not in html


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


def test_import_products_upserts(app, tmp_path):
    from shop.importer import import_file
    path = tmp_path / "items.csv"
    path.write_text("name,category,price,stock,active,description\n"
                    "Test Runner,Running,9.50,4,yes,Light\n"
                    "Vans Old Skool Black White,Lifestyle,15.00,3,yes,Updated\n"
                    ",Running,1,1,yes,missing name\n", encoding="utf-8")
    with app.app_context():
        before = db.session.scalar(db.select(db.func.count(Product.id)))
        result = import_file(path, download_images=False, log=lambda *_: None)
        assert (result["created"], result["updated"], len(result["errors"])) == (1, 1, 1)
        assert db.session.scalar(db.select(db.func.count(Product.id))) == before + 1
        vans = db.session.scalar(db.select(Product).where(Product.name.like("Vans Old Skool%")))
        assert vans.price == Decimal("15.00") and vans.description == "Updated"
        new = db.session.scalar(db.select(Product).where(Product.name == "Test Runner"))
        assert new.category == "Running" and new.image_data  # generated artwork


def test_import_replace_keeps_order_history(client, app, tmp_path):
    public_id, pid, _ = place_order(client, app, qty=1)
    path = tmp_path / "one.json"
    path.write_text('{"products": [{"name": "Only One", "price": 5, "stock": 1}]}', encoding="utf-8")
    from shop.importer import import_file
    with app.app_context():
        import_file(path, replace=True, download_images=False, log=lambda *_: None)
        assert db.session.scalars(db.select(Product.name)).all() == ["Only One"]
        order = db.session.scalar(db.select(Order).where(Order.public_id == public_id))
        assert order.items[0].product_id is None and order.items[0].product_name


def test_store_filters_and_sort(client, app):
    html = client.get("/?in_stock=1").get_data(as_text=True)
    assert "Air Jordan 1 Retro High OG Chicago Lost and Found" not in html  # stock 0
    html = client.get("/?max=80&sort=price_asc").get_data(as_text=True)
    assert "Vans Old Skool Black White" in html
    assert "Air Jordan 4 Retro Military Black" not in html
    prices = [float(x) for x in re.findall(r'<span class="price">\$([\d.]+)</span>', client.get("/?sort=price_desc").get_data(as_text=True))]
    assert prices == sorted(prices, reverse=True) and len(prices) > 5
    assert client.get("/?min=abc&sort=bogus").status_code == 200


def test_admin_dashboard(client, app):
    public_id, *_ = place_order(client, app, qty=2)
    token = csrf(client, f"/order/{public_id}/pay")
    client.post(f"/order/{public_id}/simulate-payment", data={"csrf_token": token})
    login(client)
    r = client.get("/admin/")
    html = r.get_data(as_text=True)
    assert r.status_code == 200
    assert "Revenue, last 7 days" in html and "Live activity" in html and "Sok Dara" in html
    assert 'id="admin-sidebar"' in html and 'class="admin-footer"' in html


def test_admin_restock_toggle_and_filters(client, app):
    token = login(client)
    with app.app_context():
        p = db.session.scalar(db.select(Product).where(Product.is_active.is_(True), Product.stock > 0))
        pid, stock = p.id, p.stock
    client.post(f"/admin/products/{pid}/restock", data={"csrf_token": token})
    client.post(f"/admin/products/{pid}/toggle", data={"csrf_token": token})
    with app.app_context():
        p = db.session.get(Product, pid)
        assert p.stock == stock + 5 and not p.is_active
    hidden = client.get("/admin/products?filter=hidden").get_data(as_text=True)
    assert p.name.split(" (")[0] in hidden
    sold_out = client.get("/admin/products?filter=soldout").get_data(as_text=True)
    assert "Air Jordan 1 Retro High OG Chicago Lost and Found" in sold_out
    assert client.get("/admin/products?filter=low&q=zzz").status_code == 200


def test_admin_order_search(client, app):
    public_id, *_ = place_order(client, app, qty=1)
    login(client)
    assert "Sok Dara" in client.get("/admin/orders?q=sok").get_data(as_text=True)
    assert "Sok Dara" not in client.get("/admin/orders?q=nobody").get_data(as_text=True)
    assert "Sok Dara" in client.get("/admin/orders?q=%2300001").get_data(as_text=True)


def test_pad_crop_keeps_whole_wide_photo():
    import io
    from PIL import Image
    from shop.importer import _crop_square
    buf = io.BytesIO()
    Image.new("RGB", (800, 571), (200, 0, 0)).save(buf, format="PNG")
    buf.seek(0)
    out = Image.open(_crop_square(buf, "pad"))
    assert out.width == out.height > 800  # square, nothing cut off
    assert out.getpixel((2, 2)) == (255, 255, 255)  # white margin
    assert out.getpixel((out.width // 2, out.height // 2)) == (200, 0, 0)


def test_header_menu_marks_current_section(client):
    html = client.get("/").get_data(as_text=True)
    assert 'class="mainnav"' in html and 'id="site-menu"' in html and "Under $100" in html
    assert 'id="site-search" hidden' in html  # search starts closed
    html = client.get("/?category=Running").get_data(as_text=True)
    assert html.count('href="/?category=Running" class="active"') == 2  # desktop menu + phone menu
    html = client.get("/?max=100").get_data(as_text=True)
    assert 'class="active deal"' in html


def test_header_search_open_on_results(client):
    html = client.get("/?q=jordan").get_data(as_text=True)
    assert 'id="site-search" hidden' not in html
    assert 'aria-expanded="true"' in html and 'value="jordan"' in html


def test_home_featured_pairs_and_brands(client):
    html = client.get("/").get_data(as_text=True)
    assert "data-stage" in html and html.count('class="pick"') == 4
    assert "Shop by brand" in html and 'href="/?brand=Jordan#products"' in html
    assert 'id="filters"' not in html  # the filter sidebar is gone
    # featured pairs are in stock, so the sold-out Jordan 1 is never the hero
    hero = html.split('id="stage-name"')[1].split("</h1>")[0]
    assert "Lost and Found" not in hero


def test_brand_filter_and_chip_links_keep_other_filters(client):
    html = client.get("/?brand=Jordan").get_data(as_text=True)
    assert "Air Jordan 4 Retro Military Black" in html and "Vans Old Skool" not in html
    assert "data-stage" not in html  # filtered pages skip the hero
    html = client.get("/?category=Running&in_stock=1").get_data(as_text=True)
    assert 'href="/?category=Running&amp;in_stock=1&amp;max=100#products"' in html
    assert client.get("/?brand=NotABrand").status_code == 200
