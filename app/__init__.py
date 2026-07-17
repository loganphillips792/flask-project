import os

from flask import Flask

from app.database import db
from app.models import MODELS, Book, User


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")

    from app.auth import auth, login_manager
    from app.observability import init_observability
    from app.routes import api, health
    from app.session import PeeweeSessionInterface

    app.session_interface = PeeweeSessionInterface()

    login_manager.init_app(app)
    app.register_blueprint(api)
    app.register_blueprint(auth)
    app.register_blueprint(health)

    # After the blueprints: PrometheusMetrics labels by endpoint, so it needs
    # to see the registered views.
    init_observability(app)

    with db:
        db.create_tables(MODELS, safe=True)

    @app.before_request
    def open_connection():
        db.connect(reuse_if_open=True)

    @app.teardown_request
    def close_connection(exc):
        if not db.is_closed():
            db.close()

    @app.cli.command("init-db")
    def init_db():
        """Create tables and seed test users and books."""
        with db:
            db.create_tables(MODELS, safe=True)
            seed_data()
        print("Database initialized and seeded.")
        print("Demo login: ada@example.com / password (member)")
        print("Admin login: admin@example.com / password (admin)")

    return app


DEMO_PASSWORD = "password"


def seed_data():
    users = [
        {"name": "Admin", "email": "admin@example.com", "role": "admin"},
        {"name": "Ada Lovelace", "email": "ada@example.com"},
        {"name": "Grace Hopper", "email": "grace@example.com"},
        {"name": "Alan Turing", "email": "alan@example.com"},
    ]
    books = [
        {"title": "The Pragmatic Programmer", "author": "Hunt & Thomas", "isbn": "9780135957059"},
        {"title": "Fluent Python", "author": "Luciano Ramalho", "isbn": "9781492056355"},
        {"title": "Designing Data-Intensive Applications", "author": "Martin Kleppmann", "isbn": "9781449373320"},
        {"title": "The Mythical Man-Month", "author": "Fred Brooks", "isbn": "9780201835953"},
    ]
    for user in users:
        role = user.get("role", "member")
        obj, _ = User.get_or_create(
            email=user["email"],
            defaults={"name": user["name"], "role": role},
        )
        obj.role = role
        obj.set_password(DEMO_PASSWORD)
        obj.save()
    for book in books:
        Book.get_or_create(isbn=book["isbn"], defaults={"title": book["title"], "author": book["author"]})
