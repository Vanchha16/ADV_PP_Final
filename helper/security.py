import hmac
import secrets
from functools import wraps

from flask import abort, current_app, redirect, request, session, url_for


def csrf_token():
    token = session.get("_csrf")
    if not token:
        token = session["_csrf"] = secrets.token_urlsafe(32)
    return token


def verify_csrf():
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        sent = request.form.get("csrf_token") or request.headers.get("X-CSRFToken", "")
        expected = session.get("_csrf", "")
        if not expected or not hmac.compare_digest(sent, expected):
            abort(400, description="Your session expired. Please reload the page and try again.")


def check_admin_credentials(username, password):
    cfg = current_app.config
    user_ok = hmac.compare_digest(username.encode(), cfg["ADMIN_USERNAME"].encode())
    pass_ok = hmac.compare_digest(password.encode(), cfg["ADMIN_PASSWORD"].encode())
    return user_ok and pass_ok


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("admin.login", next=request.full_path))
        return view(*args, **kwargs)
    return wrapped
