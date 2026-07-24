import logging
import random
from functools import wraps

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import (
    LoginManager,
    current_user,
    login_required,
    login_user,
    logout_user,
)

from app.models import Book, Loan, User

logger = logging.getLogger(__name__)

login_manager = LoginManager()
login_manager.login_view = "auth.login"

auth = Blueprint("auth", __name__, template_folder="../templates")


def admin_required(view):
    """Allow only authenticated users whose role is 'admin'.

    Stacks @login_required so anonymous requests still hit the login flow;
    an authenticated non-admin gets a 403.
    """

    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if getattr(current_user, "role", None) != "admin":
            abort(403)
        return view(*args, **kwargs)

    return wrapped


@login_manager.user_loader
def load_user(user_id):
    return User.get_or_none(User.id == int(user_id))


@auth.get("/")
def index():
    return redirect(url_for("auth.dashboard"))


@auth.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        user = User.get_or_none(User.email == email)
        if user is not None and user.check_password(password):
            login_user(user)
            posthog_client = current_app.extensions["posthog_client"]
            posthog_client.set(
                distinct_id=str(user.id),
                properties={"email": user.email, "name": user.name, "role": user.role},
            )
            posthog_client.capture(
                "user_logged_in",
                distinct_id=str(user.id),
                properties={"login_method": "password", "role": user.role},
            )
            session["lucky_number"] = random.randint(1, 100)
            return redirect(url_for("auth.dashboard"))
        return render_template("login.html", error="Invalid email or password.")
    return render_template("login.html")


@auth.get("/dashboard")
@login_required
def dashboard():
    return render_template(
        "dashboard.html",
        lucky_number=session.get("lucky_number"),
        users=User.select().order_by(User.name),
        books=Book.select().order_by(Book.title),
    )


@auth.post("/dashboard/loans")
@admin_required
def create_dashboard_loan():
    # Not POST /api/loans: that endpoint reads a JSON body, so a form-encoded
    # post would fall through to its first-user/first-book defaults and quietly
    # ignore both dropdowns.
    user = User.get_or_none(User.id == request.form.get("user_id", type=int))
    book = Book.get_or_none(Book.id == request.form.get("book_id", type=int))
    if user is None or book is None:
        flash("Pick a valid user and book.", "error")
        return redirect(url_for("auth.dashboard"))

    loan = Loan.create(user=user, book=book)
    current_app.extensions["posthog_client"].capture(
        "loan_created",
        distinct_id=str(current_user.id),
        properties={"creation_source": "dashboard", "actor_role": current_user.role},
    )
    logger.info("user %s has created a loan for user %s", current_user.id, user.id)
    flash(f'Loaned "{book.title}" to {user.name} — due {loan.due_date}.', "success")
    # Redirect rather than render: a refresh would otherwise re-create the loan.
    return redirect(url_for("auth.dashboard"))


@auth.get("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
