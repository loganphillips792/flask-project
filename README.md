# Flask Library API

A small Flask app demonstrating a JSON API for a library, using [peewee](https://docs.peewee-orm.com/) as the ORM with a SQLite database. It has three tables — `users`, `books`, and `loans` — and endpoints to create a loan for a user and to fetch loans as JSON.

## Project structure

```
app/
├── __init__.py   # create_app() application factory + init-db CLI command
├── database.py   # peewee SqliteDatabase instance
├── models.py     # User, Book, Loan models
└── routes.py     # /api blueprint with the endpoints
run.py            # entry point for the dev server
requirements.txt
```

## Setup

Requires Python 3.10+.

1. Create and activate a virtual environment:

   ```bash
   python3 -m venv venv
   source venv/bin/activate   # on Windows: venv\Scripts\activate
   ```

2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Initialize the database and seed test data (3 users, 4 books):

   ```bash
   flask --app run init-db
   ```

## Running the app

```bash
python run.py
```

The dev server starts on http://127.0.0.1:5000. The SQLite database is stored in `library.db` in the project root.

## API endpoints

### Create a loan — `POST /api/loans`

With no body, it creates a loan using seeded test data (first user, first book):

```bash
curl -X POST http://127.0.0.1:5000/api/loans
```

Or specify the user and book:

```bash
curl -X POST http://127.0.0.1:5000/api/loans \
  -H "Content-Type: application/json" \
  -d '{"user_id": 2, "book_id": 3}'
```

Response (`201 Created`):

```json
{
  "id": 1,
  "user": {"id": 1, "name": "Ada Lovelace", "email": "ada@example.com"},
  "book": {"id": 1, "title": "The Pragmatic Programmer", "author": "Hunt & Thomas", "isbn": "9780135957059"},
  "loaned_at": "2026-07-08T12:00:00",
  "due_date": "2026-07-22",
  "returned": false
}
```

### Get all loans — `GET /api/loans`

```bash
curl http://127.0.0.1:5000/api/loans
```

Returns a JSON list of all loans, each including its user and book.

### Get a loan by id — `GET /api/loans/<id>`

```bash
curl http://127.0.0.1:5000/api/loans/1
```

Returns the loan as JSON, or a `404` with `{"error": "Loan 1 not found"}` if it doesn't exist.
