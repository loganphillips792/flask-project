"""Admin-only catalog views: browsing books, adding them, and closing loans."""

import logging

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user
from peewee import IntegrityError

from app.auth import admin_required
from app.models import Book, Loan, User, books_with_availability

logger = logging.getLogger(__name__)

books = Blueprint("books", __name__, template_folder="../templates")


@books.get("/books")
@admin_required
def index():
    logger.info(f"admin user {current_user.email} is viewing all books")
    return render_template("books.html", books=books_with_availability())


@books.get("/books/new")
@admin_required
def new():
    return render_template("book_form.html")


@books.post("/books")
@admin_required
def create():
    title = request.form.get("title", "").strip()
    author = request.form.get("author", "").strip()
    isbn = request.form.get("isbn", "").strip()
    # type=int yields None on anything unparseable rather than raising.
    quantity = request.form.get("quantity", type=int)

    def reject(message):
        flash(message, "error")
        # Re-render rather than redirect so the admin doesn't retype the fields
        # that were already fine.
        return render_template(
            "book_form.html", title=title, author=author, isbn=isbn, quantity=quantity
        ), 400

    if not (title and author and isbn):
        return reject("Title, author and ISBN are all required.")

    if quantity is None or quantity < 1:
        return reject("Quantity must be a whole number of 1 or more.")

    if Book.get_or_none(Book.isbn == isbn) is not None:
        return reject(f"A book with ISBN {isbn} already exists.")

    try:
        book = Book.create(title=title, author=author, isbn=isbn, quantity=quantity)
    except IntegrityError:
        # Backstop for the check-then-insert race: the unique index on isbn is
        # the real guarantee, and losing it should not surface as a 500.
        return reject(f"A book with ISBN {isbn} already exists.")

    current_app.extensions["posthog_client"].capture(
        "book_created",
        distinct_id=str(current_user.id),
        properties={"creation_source": "dashboard", "actor_role": current_user.role},
    )
    logger.info(f"admin user {current_user.email} added book {book.id} ({isbn})")
    flash(f'Added "{book.title}" by {book.author}.', "success")
    # Redirect rather than render: a refresh would otherwise re-create the book.
    return redirect(url_for("books.index"))


@books.get("/books/<int:book_id>/loans")
@admin_required
def loans(book_id):
    book = Book.get_or_none(Book.id == book_id)
    if book is None:
        abort(404)
    book_loans = (
        Loan.select(Loan, User)
        .join(User)
        .where(Loan.book == book)
        .order_by(Loan.loaned_at.desc())
    )
    return render_template("book_loans.html", book=book, loans=book_loans)


@books.post("/loans/<int:loan_id>/return")
@admin_required
def return_loan(loan_id):
    loan = Loan.get_or_none(Loan.id == loan_id)
    if loan is None:
        abort(404)

    if loan.returned:
        # Idempotent: a double submit, or a stale page still showing the button,
        # must not overwrite the original return date.
        flash("That loan was already marked returned.", "error")
    else:
        loan.mark_returned()
        current_app.extensions["posthog_client"].capture(
            "loan_returned",
            distinct_id=str(current_user.id),
            properties={"actor_role": current_user.role},
        )
        logger.info(f"admin user {current_user.email} marked loan {loan.id} returned")
        flash(f'Marked "{loan.book.title}" returned from {loan.user.name}.', "success")

    # Redirect rather than render: a refresh would otherwise re-submit.
    return redirect(url_for("books.loans", book_id=loan.book_id))
