import datetime

from flask_login import UserMixin
from peewee import (
    BooleanField,
    CharField,
    DateField,
    DateTimeField,
    ForeignKeyField,
    Model,
    TextField,
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

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "author": self.author,
            "isbn": self.isbn,
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

    def to_dict(self):
        return {
            "id": self.id,
            "user": self.user.to_dict(),
            "book": self.book.to_dict(),
            "loaned_at": self.loaned_at.isoformat(),
            "due_date": self.due_date.isoformat(),
            "returned": self.returned,
        }


MODELS = [User, Book, Loan, Session]
