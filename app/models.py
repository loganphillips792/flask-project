import datetime
from zoneinfo import ZoneInfo

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

# A curated shortlist rather than the full IANA set: a ~600-entry <select> is
# unusable, and these cover the zones this library's members actually sit in.
# Anything a user posts is validated against this list before it reaches
# ZoneInfo(), so the list doubles as the allowlist.
TIMEZONES = [
    "UTC",
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Los_Angeles",
    "America/Anchorage",
    "Pacific/Honolulu",
    "America/Sao_Paulo",
    "Europe/London",
    "Europe/Paris",
    "Europe/Berlin",
    "Europe/Madrid",
    "Europe/Moscow",
    "Africa/Johannesburg",
    "Asia/Dubai",
    "Asia/Kolkata",
    "Asia/Shanghai",
    "Asia/Tokyo",
    "Asia/Singapore",
    "Australia/Sydney",
    "Pacific/Auckland",
]

TIME_FORMATS = ["12", "24"]


def utcnow_naive():
    """Naive UTC now — how every DateTimeField in the app is stored.

    SQLite has no timestamptz, so the convention is: naive values are always
    UTC, and conversion to a viewer's zone happens only at render time.
    """
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


def iso_utc(value):
    """ISO 8601 with an explicit +00:00 offset, so API clients can't misread it."""
    return value.replace(tzinfo=datetime.timezone.utc).isoformat() if value else None


class BaseModel(Model):
    class Meta:
        database = db


class User(BaseModel):
    name = CharField()
    email = CharField(unique=True)
    password_hash = CharField(null=True)
    timezone = CharField(default="UTC")
    time_format = CharField(default="12")  # "12" or "24"

    def get_role_names(self):
        """The user's role names, queried once per instance.

        Cached on the instance, not globally: g.user is a fresh instance each
        request, so the cache lives exactly one request.
        """
        if not hasattr(self, "_role_names"):
            query = (
                Role.select(Role.name)
                .join(RoleMembership)
                .where(RoleMembership.user == self)
            )
            self._role_names = {role.name for role in query}
        return self._role_names

    def has_role(self, *names):
        return bool(self.get_role_names().intersection(names))

    @property
    def is_admin(self):
        return self.has_role("admin")

    @property
    def primary_role(self):
        """A single display/analytics role for a multi-role user.

        Admin outranks everything; otherwise the first role alphabetically,
        falling back to "member" for a user with no memberships at all.
        """
        roles = self.get_role_names()
        if "admin" in roles:
            return "admin"
        return min(roles) if roles else "member"

    @property
    def initials(self):
        """Up to two letters for the nav avatar.

        Falls back to the email when the name is blank, so the circle is never
        empty — every user has an email, it's the unique key.
        """
        parts = (self.name or "").split()
        if not parts:
            return (self.email or "?")[:1].upper()
        return "".join(part[0] for part in parts[:2]).upper()

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
            "role": self.primary_role,
            "roles": sorted(self.get_role_names()),
            "timezone": self.timezone,
            "time_format": self.time_format,
        }


class Role(BaseModel):
    name = CharField(unique=True)


class RoleMembership(BaseModel):
    user = ForeignKeyField(User, backref="role_memberships", on_delete="CASCADE")
    role = ForeignKeyField(Role, backref="memberships")

    class Meta:
        # Unique pair, so re-granting a role is a no-op rather than a duplicate.
        indexes = ((("user", "role"), True),)


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
    loaned_at = DateTimeField(default=utcnow_naive)
    # A calendar date, not an instant: set in save() from the borrower's zone.
    due_date = DateField()
    returned = BooleanField(default=False)
    returned_at = DateTimeField(null=True)

    def mark_returned(self):
        """Close the loan, keeping the flag and its timestamp in step."""
        self.returned = True
        self.returned_at = utcnow_naive()
        self.save()

    def save(self, *args, **kwargs):
        # Due LOAN_PERIOD_DAYS after the loan day *on the borrower's calendar*,
        # so a loan made near midnight isn't due a day early or late for them.
        if self.due_date is None:
            loaned = self.loaned_at.replace(tzinfo=datetime.timezone.utc)
            local_day = loaned.astimezone(ZoneInfo(self.user.timezone)).date()
            self.due_date = local_day + datetime.timedelta(days=LOAN_PERIOD_DAYS)
        return super().save(*args, **kwargs)

    def to_dict(self):
        return {
            "id": self.id,
            "user": self.user.to_dict(),
            "book": self.book.to_dict(),
            "loaned_at": iso_utc(self.loaned_at),
            "due_date": self.due_date.isoformat(),
            "returned": self.returned,
            "returned_at": iso_utc(self.returned_at),
        }


class ChatMessage(BaseModel):
    user = ForeignKeyField(User, backref="chat_messages", on_delete="CASCADE")
    body = TextField()
    # Naive UTC, like every timestamp; rendered through user_time.
    created_at = DateTimeField(default=utcnow_naive, index=True)

    def to_dict(self):
        return {
            "id": self.id,
            "user": self.user.to_dict(),
            "body": self.body,
            "created_at": iso_utc(self.created_at),
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


MODELS = [User, Role, RoleMembership, Book, Loan, Session, ChatMessage]
