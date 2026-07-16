import datetime

from flask import Blueprint, jsonify, request

from app.models import Book, Loan, User

api = Blueprint("api", __name__, url_prefix="/api")

LOAN_PERIOD_DAYS = 14


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

    loan = Loan.create(
        user=user,
        book=book,
        due_date=datetime.date.today() + datetime.timedelta(days=LOAN_PERIOD_DAYS),
    )
    return jsonify(loan.to_dict()), 201
