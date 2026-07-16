#!/bin/sh
set -e

# seed_data() is get_or_create-based, so this is idempotent across restarts and
# safe to run on every boot of a container that already has data.
if [ "${SEED_DB:-0}" = "1" ]; then
  flask --app run init-db
fi

exec "$@"
