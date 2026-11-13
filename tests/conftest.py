import re

import pytest

from shop import create_app
from shop.extensions import db


@pytest.fixture
def app(tmp_path):
    app = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'test.db'}",
        "PAYMENT_DEMO_MODE": True,
        "BAKONG_TOKEN": "",
        "BAKONG_ACCOUNT_ID": "test_shop@aclb",
        "ADMIN_USERNAME": "admin",
        "ADMIN_PASSWORD": "secret",
    })
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def csrf(client, url="/"):
    html = client.get(url).get_data(as_text=True)
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
