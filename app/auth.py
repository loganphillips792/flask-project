import random

from flask import (
    Blueprint,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import (
    LoginManager,
    login_required,
    login_user,
    logout_user,
)

from app.models import User

login_manager = LoginManager()
login_manager.login_view = "auth.login"

auth = Blueprint("auth", __name__, template_folder="../templates")


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
            session["lucky_number"] = random.randint(1, 100)
            return redirect(url_for("auth.dashboard"))
        return render_template("login.html", error="Invalid email or password.")
    return render_template("login.html")


@auth.get("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html", lucky_number=session.get("lucky_number"))


@auth.get("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
