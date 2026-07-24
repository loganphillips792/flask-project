# Flask Library API

A small Flask app demonstrating a JSON API for a library, using [peewee](https://docs.peewee-orm.com/) as the ORM with a SQLite database. It has three tables — `users`, `books`, and `loans` — and endpoints to create a loan for a user and to fetch loans as JSON.

## Project structure

```
app/
├── __init__.py      # create_app() application factory + init-db CLI command
├── auth.py          # login/logout/dashboard blueprint (flask-login)
├── database.py      # peewee SqliteDatabase instance
├── models.py        # User, Book, Loan, Session models
├── observability.py # metrics, JSON logging and tracing setup
├── routes.py        # /api blueprint with the endpoints, plus /health
└── session.py       # server-side sessions stored via peewee
templates/           # login, dashboard, book catalog and add-book pages
observability/       # Prometheus, Grafana, Loki, Promtail and Tempo stack
compose.yaml         # includes observability/ so `docker compose up` works from the root
Dockerfile
docker-entrypoint.sh # seeds the DB when SEED_DB=1, then starts gunicorn
run.py               # entry point for the dev server
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

3. Initialize the database and seed test data (4 users, 4 books — see [Users and roles](#users-and-roles)):

   ```bash
   flask --app run init-db
   ```

## Running the app

```bash
python run.py
```

The dev server starts on http://127.0.0.1:5001. The SQLite database is stored in `library.db` in the project root.

## Users and roles

Every user has a `role` field (`app/models.py`) that is either `member` (the default for new users) or `admin`. Authentication is handled by flask-login; the role check itself lives in the `admin_required` decorator in `app/auth.py`, which stacks `@login_required` so anonymous requests get redirected to the login page while a logged-in non-admin gets a `403`.

### Seeded accounts

`flask --app run init-db` creates these four users:

| Name | Email | Password | Role |
|-|-|-|-|
| Admin | `admin@example.com` | `password` | `admin` |
| Ada Lovelace | `ada@example.com` | `password` | `member` |
| Grace Hopper | `grace@example.com` | `password` | `member` |
| Alan Turing | `alan@example.com` | `password` | `member` |

They all share the same password, set by `DEMO_PASSWORD` in `app/__init__.py`. These are throwaway local demo credentials — stored hashed via werkzeug, but obviously not something to carry into a deployed environment.

Seeding is idempotent — re-running `init-db` resets each seeded user's password and role but leaves any users you added yourself alone.

### What each role can do

| Area | Member | Admin |
|-|-|-|
| Log in, view `/dashboard` | ✅ | ✅ |
| Create a loan (dashboard form or `POST /api/loans`) | ❌ | ✅ (if a copy is free) |
| Browse the catalog at `/books` | ❌ | ✅ |
| View a book's loan history at `/books/<id>/loans` | ❌ | ✅ |
| Mark a loan returned | ❌ | ✅ |
| Add a book at `/books/new` | ❌ | ✅ |

Members still see the dashboard's "Create a loan" card, rendered locked with a 🔒 rather than hidden, so the feature is discoverable. The nav bar takes the opposite approach and omits the book links entirely for members, since those routes would only return a `403`.

Note that the read-only loan endpoints — `GET /api/loans` and `GET /api/loans/<id>` — carry no auth decorator at all, so they are reachable without logging in. Only `POST /api/loans` is admin-gated.

## Book quantity and availability

Each book carries a `quantity` — how many copies the library owns. **Available to loan** is `quantity` minus the book's outstanding (unreturned) loans, and the `/books` table shows all three numbers. A book with nothing left is greyed out in the table and appears disabled in the dashboard's loan dropdown.

Both loan-creation paths refuse to over-loan:

| Path | When exhausted |
|-|-|
| Dashboard loan form | Redirects back with an error flash, no loan created |
| `POST /api/loans` | `409 Conflict` with a JSON `error`, no loan created |

The dropdown's `disabled` options are only a hint — the server re-checks on every submit, so the rule holds even if the form is bypassed.

### Returning a book

Each outstanding loan on `/books/<id>/loans` carries a **Mark as returned** button. Marking a loan returned stamps `returned_at` and frees the copy immediately — the book's availability goes back up and it becomes selectable in the loan dropdown again. The action is admin-only and idempotent: submitting twice (a double-click, or a stale page) reports that the loan was already returned rather than overwriting the original date.

Returned loans stay in the table as history. Any loan returned before this feature existed shows `—` under "Returned on" — the timestamp genuinely wasn't recorded, and it isn't backfilled with a made-up date.

Quantity is set when adding a book at `/books/new` (minimum 1, defaults to 1). There is no UI for changing it afterwards; use the shell, as with roles below. Seeded books get 3 / 2 / 2 / 1 copies, and — like seeded user passwords — `init-db` resets those quantities on every run, so a manual change to a *seeded* title won't survive re-seeding. Books you add yourself are never touched.

### A note on schema changes

`create_app()` calls `create_tables(safe=True)`, which only creates *missing tables* — it never adds a column to a table that already exists. New columns therefore need a migration, handled by `ensure_schema()` in `app/__init__.py`: on every startup it walks `COLUMN_MIGRATIONS`, and for each entry issues a plain `ALTER TABLE … ADD COLUMN` if the column isn't there yet. Adding a column is one line in that list.

It currently covers `user.role`, `book.quantity` and `loan.returned_at`. The first matters for any database created before roles were introduced — without it, *every login* fails with `no such column: t1.role`.

It deliberately does not use `playhouse.migrate` — that helper rebuilds the table to apply `NOT NULL`, and the rebuild fails against the `foreign_keys=1` pragma because `loan.book_id` references `book`. Follow the same pattern for any future column.

### Promoting a user to admin

There's no UI for changing roles. Do it from a shell:

```bash
flask --app run shell
```

```python
from app.models import User
u = User.get(User.email == "grace@example.com")
u.role = "admin"
u.save()
```

## Running with the observability stack

The `observability/` directory runs the app in Docker alongside Prometheus (metrics), Loki + Promtail (logs), Tempo (traces) and Grafana (dashboards). Requires Docker Desktop.

1. Build and start everything, from the project root:

   ```bash
   docker compose up --build
   ```

   That one command brings up the app and all five observability services, and
   seeds the database on the way up — no second terminal needed. Log in with
   `ada@example.com` / `password`.

2. Generate some traffic:

   ```bash
   curl -X POST http://127.0.0.1:5001/api/loans
   curl http://127.0.0.1:5001/api/loans
   ```

3. Open Grafana at http://localhost:3001 (`admin` / `secretpassword`) and go to the **Library App** dashboard.

Once running, these are the pieces:

| Service | URL |
|-|-|
| Flask app | http://localhost:5001 |
| Grafana | http://localhost:3001 (`admin` / `secretpassword`) |
| Prometheus | http://localhost:9090 |
| Tempo | http://localhost:3200 |
| Loki | http://localhost:3100 |

The app exposes `/metrics` for Prometheus and `/health` for a dependency-free liveness check.

### Applying code changes

The Dockerfile bakes the source in with `COPY . .`, so there's no live mount — after editing any Python or template file, rebuild and recreate just the app container:

```bash
docker compose up -d --build flask-app
```

The five observability services keep running untouched. The database lives on a named volume, so it survives the rebuild. Follow the logs to confirm gunicorn came back up cleanly:

```bash
docker compose logs -f flask-app
```

For faster iteration on app behavior alone, run the dev server directly — `python run.py` auto-reloads on save — but it runs without the observability backends, so use Docker when you want changes to show up in Grafana.

**The containerized database is separate from your local one.** In Docker the app writes to `/data/library.db` on the `library-data` named volume, so it neither reads nor writes the `library.db` in the project root. Seeding one does not seed the other. So if you create a loan through the app and then find nothing in the project-root `library.db`, that's why — the data is in the volume, not the local file.

To inspect the container's data, either query it live (`curl http://127.0.0.1:5001/api/loans`, or `docker compose exec flask-app python ...`), or copy the file out to open it in a SQLite GUI:

```bash
docker compose cp flask-app:/data/library.db ./container-library.db
```

That's a point-in-time copy, not a live view. To reset the container's data:

```bash
docker compose down -v
```

The root `compose.yaml` only `include:`s `observability/docker-compose.yml`, which is where the services are actually defined. Seeding runs from `docker-entrypoint.sh` before gunicorn starts, gated on `SEED_DB=1` (set on the `flask-app` service) so the image doesn't create demo users anywhere else. It's idempotent, so it re-runs harmlessly on every restart.

### What's wired up

- **Metrics** — `prometheus-flask-exporter` serves `/metrics` on the app's own port; Prometheus scrapes it every 10s. Alongside the HTTP metrics, the app exports SQLite query metrics (see below).
- **Logs** — the app logs JSON to stdout; Promtail discovers the container over the Docker socket and ships lines to Loki. Query them with `{service_name="flask-app"} | json`.
- **Traces** — OpenTelemetry instruments Flask and sqlite3, exporting spans to Tempo over OTLP. Each log line carries the `trace_id`, so you can jump from a span straight to its logs in Grafana. Note: the sqlite3 instrumentation only captures connection-setup PRAGMAs, not peewee's queries (they run through a cursor it doesn't wrap) — so query visibility comes from the SQLite metrics below, not from traces.

### SQLite metrics

`app/db_metrics.py` wraps peewee's `execute_sql` (the chokepoint every query passes through) and exposes these on `/metrics`:

- `db_queries_total{operation,status}` — counter of queries by SQL operation (`SELECT`/`INSERT`/`UPDATE`/`DELETE`/`PRAGMA`/`BEGIN`/`COMMIT`/`CREATE`) and `ok`/`error`.
- `db_query_duration_seconds{operation}` — histogram of query duration (sub-millisecond buckets).
- `db_file_size_bytes{file}` and `db_table_rows{table}` — gauges sampled at scrape time by a custom collector, which reads via a raw sqlite3 connection so it neither inflates the query counters nor emits spans.

Each query is also logged (logger `app.db`, one JSON line per statement) with its `operation`, `duration_ms`, and `status`. The SQL logged is the parameterized template — placeholders, not values — so parameter values are never written to the logs.

The **SQLite** dashboard in Grafana (provisioned from `observability/grafana/provisioning/dashboards/sqlite.json`) charts query rate and latency percentiles by operation, queries per HTTP request, DB file size, and row counts per table. Its **Recent queries** panel lists every statement executed, newest first, from the `app.db` logs:

```logql
{service_name="flask-app"} | json | logger="app.db" | line_format "{{.operation}}  {{.duration_ms}}ms  {{.msg}}"
```

(The main Library App dashboard's log panel filters these out with `logger!="app.db"` so it isn't flooded by query lines.) A true per-statement "slowest queries" ranking would need query-level tracing, which is not enabled.

### Querying logs in Loki

Logs are JSON, one object per line. In Grafana → **Explore** with the Loki data source (or a Loki panel), run these LogQL queries.

All log lines from the app:

```logql
{service_name="flask-app"} | json
```

All "loan created" logs (emitted by the dashboard form):

```logql
{service_name="flask-app"} |= "created a loan"
```

Parse the JSON fields, so you can add columns or filter on them:

```logql
{service_name="flask-app"} | json | msg =~ `.*created a loan.*`
```

Only loans created by a specific user (e.g. user 2):

```logql
{service_name="flask-app"} | json | logger="app.auth" | msg =~ `user 2 has created a loan.*`
```

Count loans created over time (turns it into a graph):

```logql
sum(count_over_time({service_name="flask-app"} |= "created a loan" [5m]))
```

Reach for the `|=` line filter by default — it matches the substring before any JSON parsing, so it's the cheapest option. Add `| json` only when you want individual fields (`trace_id`, `uri`, `logger`) broken out in the table, or need to filter on one.

## API endpoints

### Create a loan — `POST /api/loans`

With no body, it creates a loan using seeded test data (first user, first book):

```bash
curl -X POST http://127.0.0.1:5001/api/loans
```

Returns `409 Conflict` with `{"error": "No copies of \"…\" are available"}` if every copy of the book is already on loan — see [Book quantity and availability](#book-quantity-and-availability).

Or specify the user and book:

```bash
curl -X POST http://127.0.0.1:5001/api/loans \
  -H "Content-Type: application/json" \
  -d '{"user_id": 2, "book_id": 3}'
```

Response (`201 Created`):

```json
{
  "id": 1,
  "user": {"id": 1, "name": "Ada Lovelace", "email": "ada@example.com"},
  "book": {
    "id": 1,
    "title": "The Pragmatic Programmer",
    "author": "Hunt & Thomas",
    "isbn": "9780135957059",
    "quantity": 3,
    "copies_available": 2
  },
  "loaned_at": "2026-07-08T12:00:00",
  "due_date": "2026-07-22",
  "returned": false,
  "returned_at": null
}
```

### Get all loans — `GET /api/loans`

```bash
curl http://127.0.0.1:5001/api/loans
```

Returns a JSON list of all loans, each including its user and book.

### Get a loan by id — `GET /api/loans/<id>`

```bash
curl http://127.0.0.1:5001/api/loans/1
```

Returns the loan as JSON, or a `404` with `{"error": "Loan 1 not found"}` if it doesn't exist.
