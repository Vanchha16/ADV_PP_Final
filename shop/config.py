import os

from dotenv import load_dotenv

load_dotenv()


def _bool(name, default=None):
    raw = os.environ.get(name, "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return default


def _database_url():
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        return None  # filled in by create_app with an instance-folder SQLite path
    # Heroku/Render style URLs -> SQLAlchemy + psycopg3 driver
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me")
    SQLALCHEMY_DATABASE_URI = _database_url()
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
    MAX_CONTENT_LENGTH = 6 * 1024 * 1024  # upload limit
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    SHOP_NAME = os.environ.get("SHOP_NAME", "Sneakers Shop")
    ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")

    BAKONG_TOKEN = os.environ.get("BAKONG_TOKEN", "").strip()
    BAKONG_API_URL = os.environ.get("BAKONG_API_URL", "https://api-bakong.nbc.gov.kh/v1").rstrip("/")
    BAKONG_PROXY_KEY = os.environ.get("BAKONG_PROXY_KEY", "").strip()
    BAKONG_ACCOUNT_ID = os.environ.get("BAKONG_ACCOUNT_ID", "demo_shop@aclb").strip()
    BAKONG_MERCHANT_NAME = os.environ.get("BAKONG_MERCHANT_NAME", SHOP_NAME).strip()
    BAKONG_MERCHANT_CITY = os.environ.get("BAKONG_MERCHANT_CITY", "Phnom Penh").strip()
    BAKONG_PHONE = os.environ.get("BAKONG_PHONE", "").strip()
    KHQR_CURRENCY = os.environ.get("KHQR_CURRENCY", "USD").strip().upper()
    QR_TTL_MINUTES = int(os.environ.get("QR_TTL_MINUTES", "10"))
    PAYMENT_DEMO_MODE = _bool("PAYMENT_DEMO_MODE", default=not BAKONG_TOKEN)

    AUTO_SEED = _bool("AUTO_SEED", default=True)
    SEED_DOWNLOAD_IMAGES = _bool("SEED_DOWNLOAD_IMAGES", default=True)
