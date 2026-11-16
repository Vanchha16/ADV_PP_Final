from flask import flash, redirect, render_template, request, session, url_for
from sqlalchemy import func

from extensions import db
from helper.security import check_admin_credentials
from models import Order

from . import bp


@bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("is_admin"):
        return redirect(url_for("admin.dashboard"))
    if request.method == "POST":
        if check_admin_credentials(request.form.get("username", ""), request.form.get("password", "")):
            session["is_admin"] = True
            flash("Welcome back!", "success")
            nxt = request.args.get("next", "")
            if nxt.startswith("/admin") and not nxt.startswith("//"):
                return redirect(nxt)
            return redirect(url_for("admin.dashboard"))
        flash("Invalid username or password.", "danger")
    return render_template("admin/page/login/login.html")


@bp.post("/logout")
def logout():
    session.pop("is_admin", None)
    flash("You have been logged out.", "info")
    return redirect(url_for("admin.login"))


@bp.app_context_processor
def admin_globals():
    if not session.get("is_admin") or not request.blueprint == "admin":
        return {}
    pending = db.session.scalar(db.select(func.count(Order.id)).where(Order.status == Order.STATUS_PENDING))
    return {"sidebar_pending": pending}
