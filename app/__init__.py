"""Flask application factory with isolated role/admin login routes, logging, and security headers."""

import logging
from logging.handlers import RotatingFileHandler
import os
from flask import Flask, abort, redirect, render_template

from .ai_engine import ai_engine
from .config import Config
from .db import close_db, get_db, init_db
from .routes_analytics import analytics_bp
from .routes_auth import auth_bp
from .routes_requests import requests_bp
from .routes_workflows import workflows_bp

ALLOWED_LOGIN_PORTALS = {"staff", "admin"}


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)

    os.makedirs(app.config["LOG_DIR"], exist_ok=True)
    os.makedirs(app.config["UPLOAD_DIR"], exist_ok=True)

    if not app.testing:
        handler = RotatingFileHandler(
            os.path.join(app.config["LOG_DIR"], "app.log"),
            maxBytes=1_048_576,
            backupCount=3,
        )
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        handler.setLevel(logging.INFO)
        app.logger.addHandler(handler)
        app.logger.setLevel(logging.INFO)

    app.teardown_appcontext(close_db)

    @app.after_request
    def apply_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

    app.register_blueprint(auth_bp)
    app.register_blueprint(requests_bp)
    app.register_blueprint(workflows_bp)
    app.register_blueprint(analytics_bp)

    @app.route("/")
    @app.route("/login")
    def index():
        return render_template("index.html", portal_role="staff")

    @app.route("/login/<portal_role>")
    def portal_login(portal_role: str):
        role = portal_role.strip().lower()
        if role == "admin":
            return render_template("index.html", portal_role="admin")
        if role in ("requester", "manager", "approver", "hr", "staff"):
            return redirect("/login", code=302)
        abort(404)

    with app.app_context():
        init_db(seed=True)
        ai_engine.train_from_db(get_db())

    return app
