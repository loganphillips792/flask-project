import atexit
import os
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from flask import Flask
from flask_login import current_user
from posthog import Posthog

from app.database import db
from app.models import MODELS, Book, User


def create_app():
    load_dotenv()
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")

    posthog_client = Posthog(
        os.environ["POSTHOG_PROJECT_TOKEN"],
        host=os.environ["POSTHOG_HOST"],
        enable_exception_autocapture=True,
    )
    app.extensions["posthog_client"] = posthog_client
    atexit.register(posthog_client.shutdown)

    # Expose the public project token to templates so posthog-js (in base.html)
    # can capture client-side $pageview events — the basis for unique-visitor
    # analytics, including anonymous, logged-out visitors the Python SDK never sees.
    @app.context_processor
    def inject_posthog_config():
        return {
            "posthog_token": os.environ["POSTHOG_PROJECT_TOKEN"],
            "posthog_host": os.environ["POSTHOG_HOST"],
        }

    # Every stored timestamp renders through here, so a single preference change
    # moves the whole app rather than each template formatting its own way.
    @app.template_filter("user_time")
    def user_time(value):
        """Render a DB timestamp in the viewer's timezone and clock format.

        Loan timestamps are naive `datetime.now()` values — server-local, not
        UTC — so they're localised to the server zone before being converted.
        """
        if value is None:
            return "—"
        tz = ZoneInfo(getattr(current_user, "timezone", None) or "UTC")
        aware = value.astimezone() if value.tzinfo is None else value
        if getattr(current_user, "time_format", "12") == "24":
            pattern = "%Y-%m-%d %H:%M"
        else:
            pattern = "%Y-%m-%d %I:%M %p"
        return aware.astimezone(tz).strftime(pattern)

    from app.auth import auth, login_manager
    from app.books import books
    from app.observability import init_observability
    from app.routes import api, health
    from app.session import PeeweeSessionInterface

    app.session_interface = PeeweeSessionInterface()

    login_manager.init_app(app)
    app.register_blueprint(api)
    app.register_blueprint(auth)
    app.register_blueprint(books)
    app.register_blueprint(health)

    # After the blueprints: PrometheusMetrics labels by endpoint, so it needs
    # to see the registered views.
    init_observability(app)

    with db:
        db.create_tables(MODELS, safe=True)
        ensure_schema()

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
            ensure_schema()
            seed_data()
        print("Database initialized and seeded.")
        print("Demo login: ada@example.com / password (member)")
        print("Admin login: admin@example.com / password (admin)")

    return app


# Plain ALTER statements: SQLite accepts a NOT NULL column when it carries a
# non-null default, and backfills existing rows with it. Deliberately not
# playhouse.migrate — its add_column rebuilds the table to apply NOT NULL, and
# the rebuild fails the foreign_keys pragma via loan.book_id.
COLUMN_MIGRATIONS = [
    # Predates the quantity work: databases created before roles existed have no
    # user.role, and every login fails on `no such column: t1.role`.
    ("user", "role", "ALTER TABLE \"user\" ADD COLUMN role VARCHAR(255) NOT NULL DEFAULT 'member'"),
    ("book", "quantity", "ALTER TABLE book ADD COLUMN quantity INTEGER NOT NULL DEFAULT 1"),
    ("loan", "returned_at", "ALTER TABLE loan ADD COLUMN returned_at DATETIME"),
    ("user", "timezone", "ALTER TABLE \"user\" ADD COLUMN timezone VARCHAR(255) NOT NULL DEFAULT 'UTC'"),
    ("user", "time_format", "ALTER TABLE \"user\" ADD COLUMN time_format VARCHAR(255) NOT NULL DEFAULT '12'"),
]


def ensure_schema():
    """Add columns that `create_tables(safe=True)` can't retrofit.

    create_tables only creates *missing tables* — it never alters an existing
    one, so a database created before a field was added keeps the old columns
    and every query for the new one fails. Runs on every startup and is a no-op
    once applied.
    """
    for table, column, ddl in COLUMN_MIGRATIONS:
        if column not in {existing.name for existing in db.get_columns(table)}:
            db.execute_sql(ddl)


DEMO_PASSWORD = "password"


def seed_data():
    users = [
        {"name": "Admin", "email": "admin@example.com", "role": "admin"},
        {"name": "Ada Lovelace", "email": "ada@example.com"},
        {"name": "Grace Hopper", "email": "grace@example.com"},
        {"name": "Alan Turing", "email": "alan@example.com"},
    ]
    books = [
        {"title": "The Pragmatic Programmer", "author": "Hunt & Thomas", "isbn": "9780135957059", "quantity": 3},
        {"title": "Fluent Python", "author": "Luciano Ramalho", "isbn": "9781492056355", "quantity": 2},
        {"title": "Designing Data-Intensive Applications", "author": "Martin Kleppmann", "isbn": "9781449373320", "quantity": 2},
        {"title": "The Mythical Man-Month", "author": "Fred Brooks", "isbn": "9780201835953", "quantity": 1},
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
        obj, _ = Book.get_or_create(
            isbn=book["isbn"],
            defaults={"title": book["title"], "author": book["author"], "quantity": book["quantity"]},
        )
        # Reset stock on the demo titles the same way user passwords are reset,
        # so the seeded quantities show up on a database that predates them.
        obj.quantity = book["quantity"]
        obj.save()
