from extensions import db


class AppMeta(db.Model):
    __tablename__ = "app_meta"

    key = db.Column(db.String(50), primary_key=True)
    value = db.Column(db.String(200), nullable=True)
