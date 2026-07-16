FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# /data must exist and be owned by appuser *in the image*: Docker seeds a fresh
# named volume from the image's ownership. Created by the mount instead, it
# would be root-owned and create_tables() would fail at startup.
RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /data \
    && chown appuser:appuser /data \
    && chmod +x /app/docker-entrypoint.sh
USER appuser

EXPOSE 5001

# Seeds the database first when SEED_DB=1, then execs the CMD below.
ENTRYPOINT ["/app/docker-entrypoint.sh"]

# gunicorn imports the module-level `app` from run.py rather than calling
# app.run(), so the dev server's debug reloader (which forks and would
# double-initialize the OTel SDK) never enters the picture.
#
# --workers 1 is load-bearing: prometheus_client holds counters in per-process
# memory, so multiple workers would make /metrics return whichever worker
# happened to serve the scrape. It also matches SQLite's single-writer model.
CMD ["gunicorn", "--bind", "0.0.0.0:5001", "--workers", "1", "--threads", "4", "run:app"]
