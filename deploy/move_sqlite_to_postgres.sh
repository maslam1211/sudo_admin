#!/usr/bin/env bash
# Copy every row from the Django SQLite database into PostgreSQL, then compare
# row counts table by table. Nothing is deleted: the SQLite file is only read.
#
#   DATABASE_URL=postgres://sudotag:...@127.0.0.1:5432/sudotag \
#     deploy/move_sqlite_to_postgres.sh /path/to/db.sqlite3
#
# Run with the web service stopped (or in a maintenance window) so no rows are
# written to SQLite after the copy. The PostgreSQL database must be empty.
set -euo pipefail

SQLITE_FILE="${1:?usage: $0 /path/to/db.sqlite3}"
: "${DATABASE_URL:?set DATABASE_URL to the PostgreSQL database}"
cd "$(dirname "$0")/.."
PY="${PY:-python3}"
for v in venv .venv env; do [ -x "$v/bin/python" ] && PY="$v/bin/python" && break; done
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "== 1. bring SQLite copy up to date (migrations on a copy, original untouched)"
cp "$SQLITE_FILE" "$WORK/source.sqlite3"
env -u DATABASE_URL SQLITE_PATH="$WORK/source.sqlite3" "$PY" manage.py migrate --noinput >/dev/null

echo "== 2. dump all rows"
env -u DATABASE_URL SQLITE_PATH="$WORK/source.sqlite3" "$PY" manage.py dumpdata \
  --natural-foreign --natural-primary \
  --exclude contenttypes --exclude auth.permission \
  --indent 0 -o "$WORK/data.json"

echo "== 3. create tables in PostgreSQL and load"
"$PY" manage.py migrate --noinput >/dev/null
"$PY" manage.py loaddata "$WORK/data.json"

echo "== 4. compare row counts"
env -u DATABASE_URL SQLITE_PATH="$WORK/source.sqlite3" "$PY" manage.py shell -c "
from django.apps import apps
for m in apps.get_models():
    if m._meta.app_label in ('contenttypes',) or m._meta.label == 'auth.Permission': continue
    print(m._meta.label, m.objects.count())" | sort > "$WORK/sqlite.counts"
"$PY" manage.py shell -c "
from django.apps import apps
for m in apps.get_models():
    if m._meta.app_label in ('contenttypes',) or m._meta.label == 'auth.Permission': continue
    print(m._meta.label, m.objects.count())" | sort > "$WORK/pg.counts"
if diff -u "$WORK/sqlite.counts" "$WORK/pg.counts"; then
  echo "OK: every table has the same number of rows ($(awk '{s+=$2} END {print s}' "$WORK/pg.counts") rows)."
else
  echo "MISMATCH: see diff above. PostgreSQL was not switched on; fix and re-run on an empty database." >&2
  exit 1
fi
