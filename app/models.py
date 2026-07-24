import datetime

from flask_login import UserMixin
from peewee import (
    JOIN,
    BooleanField,
    CharField,
    DateField,
    DateTimeField,
    ForeignKeyField,
    IntegerField,
    Model,
    TextField,
    fn,
)
from werkzeug.security import check_password_hash, generate_password_hash

from app.database import db


LOAN_PERIOD_DAYS = 14


def _default_due_date():
    return datetime.date.today() + datetime.timedelta(days=LOAN_PERIOD_DAYS)


class BaseModel(Model):
    class Meta:
        database = db


class User(UserMixin, BaseModel):
    name = CharField()
    email = CharField(unique=True)
    password_hash = CharField(null=True)
    role = CharField(default="member")

    @property
    def is_admin(self):
        return self.role == "admin"

    def set_password(self, raw):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw):
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, raw)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "role": self.role,
        }


class Book(BaseModel):
    title = CharField()
    author = CharField()
    isbn = CharField(unique=True)
    quantity = IntegerField(default=1)

    @property
    def copies_available(self):
        # Prefer the aggregate from books_with_availability() when this instance
        # carries it, so rendering a table doesn't fire a COUNT per row.
        out = getattr(self, "copies_out", None)
        if out is None:
            out = copies_on_loan(self)
        # Clamped: stock lowered below what's already out should read 0, not -1.
        return max(0, self.quantity - out)

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "author": self.author,
            "isbn": self.isbn,
            "quantity": self.quantity,
            "copies_available": self.copies_available,
        }


class Session(BaseModel):
    sid = CharField(unique=True, index=True)
    data = TextField()
    expiry = DateTimeField(null=True)


class Loan(BaseModel):
    user = ForeignKeyField(User, backref="loans")
    book = ForeignKeyField(Book, backref="loans")
    loaned_at = DateTimeField(default=datetime.datetime.now)
    due_date = DateField(default=_default_due_date)
    returned = BooleanField(default=False)
    returned_at = DateTimeField(null=True)

    def mark_returned(self):
        """Close the loan, keeping the flag and its timestamp in step."""
        self.returned = True
        self.returned_at = datetime.datetime.now()
        self.save()

    def to_dict(self):
        return {
            "id": self.id,
            "user": self.user.to_dict(),
            "book": self.book.to_dict(),
            "loaned_at": self.loaned_at.isoformat(),
            "due_date": self.due_date.isoformat(),
            "returned": self.returned,
            "returned_at": self.returned_at.isoformat() if self.returned_at else None,
        }


def books_with_availability():
    """Every book, annotated with `copies_out` — its outstanding loans.

    A left outer join, so books nobody has borrowed still appear, with the join
    condition narrowed to unreturned loans: `copies_out` is a live count, not a
    lifetime one.
    """
    return (
        Book.select(Book, fn.COUNT(Loan.id).alias("copies_out"))
        .join(Loan, JOIN.LEFT_OUTER, on=((Loan.book == Book.id) & (Loan.returned == False)))
        .group_by(Book)
        .order_by(Book.title)
    )


def copies_on_loan(book):
    """How many copies of `book` are currently out."""
    return Loan.select().where((Loan.book == book) & (Loan.returned == False)).count()


MODELS = [User, Book, Loan, Session]
