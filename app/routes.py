from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user

from app.auth import admin_required
from app.database import db
from app.models import Book, Loan, User, copies_on_loan

api = Blueprint("api", __name__, url_prefix="/api")
health = Blueprint("health", __name__)


@health.get("/health")
def healthcheck():
    # Deliberately does not touch the database: a locked SQLite file should not
    # cascade into a container restart loop.
    return jsonify({"status": "ok"})


@api.get("/loans")
def get_loans():
    loans = Loan.select(Loan, User, Book).join(User).switch(Loan).join(Book)
    return jsonify([loan.to_dict() for loan in loans])


@api.get("/loans/<int:loan_id>")
def get_loan(loan_id):
    loan = Loan.get_or_none(Loan.id == loan_id)
    if loan is None:
        return jsonify({"error": f"Loan {loan_id} not found"}), 404
    return jsonify(loan.to_dict())


@api.post("/loans")
@admin_required
def create_loan():
    data = request.get_json(silent=True) or {}

    if "user_id" in data:
        user = User.get_or_none(User.id == data["user_id"])
        if user is None:
            return jsonify({"error": f"User {data['user_id']} not found"}), 404
    else:
        user = User.select().first()
        if user is None:
            return jsonify({"error": "No users exist; run `flask --app run init-db` to seed test data"}), 400

    if "book_id" in data:
        book = Book.get_or_none(Book.id == data["book_id"])
        if book is None:
            return jsonify({"error": f"Book {data['book_id']} not found"}), 404
    else:
        book = Book.select().first()
        if book is None:
            return jsonify({"error": "No books exist; run `flask --app run init-db` to seed test data"}), 400

    # Same availability rule as the dashboard form; 409 because the request is
    # well-formed and it's the current state that forbids it.
    with db.atomic():
        if copies_on_loan(book) >= book.quantity:
            return jsonify({"error": f'No copies of "{book.title}" are available'}), 409
        loan = Loan.create(user=user, book=book)

    current_app.extensions["posthog_client"].capture(
        "loan_created",
        distinct_id=str(current_user.id),
        properties={"creation_source": "api", "actor_role": current_user.role},
    )
    return jsonify(loan.to_dict()), 201
