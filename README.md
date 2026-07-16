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
templates/           # login and dashboard pages
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

3. Initialize the database and seed test data (3 users, 4 books):

   ```bash
   flask --app run init-db
   ```

## Running the app

```bash
python run.py
```

The dev server starts on http://127.0.0.1:5001. The SQLite database is stored in `library.db` in the project root.

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
  "book": {"id": 1, "title": "The Pragmatic Programmer", "author": "Hunt & Thomas", "isbn": "9780135957059"},
  "loaned_at": "2026-07-08T12:00:00",
  "due_date": "2026-07-22",
  "returned": false
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
