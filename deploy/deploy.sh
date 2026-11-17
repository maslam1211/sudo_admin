#!/usr/bin/env bash
# Deploy the latest main on the VPS (run as root from anywhere):
#     sudo bash /path/to/sudo_admin/deploy/deploy.sh
# Never touches /etc/sudotag/sudotag.env (production settings live there).
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"
SERVICE="${SERVICE:-$(systemctl list-unit-files --type=service --no-legend | awk '{print $1}' | grep -iE 'gunicorn|sudo' | head -1)}"
OWNER="$(stat -c %U "$PROJECT_DIR")"

PY=python3
for v in venv .venv env; do [ -x "$PROJECT_DIR/$v/bin/python" ] && PY="$PROJECT_DIR/$v/bin/python" && break; done

echo "== pull";        sudo -u "$OWNER" git pull --ff-only
echo "== packages";    "$PY" -m pip install -q -r requirements.txt
echo "== migrate";     "$PY" manage.py migrate --noinput
echo "== static";      "$PY" manage.py collectstatic --noinput >/dev/null
echo "== restart $SERVICE"; systemctl restart "$SERVICE"

for i in $(seq 1 30); do
  CODE="$(curl -s -o /dev/null -w '%{http_code}' https://sudotag.com/admin/login/ || true)"
  case "$CODE" in 200|301|302) echo "live: HTTP $CODE  ($(git log --oneline -1))"; exit 0;; esac
  sleep 2
done
echo "site not answering (HTTP $CODE). Last errors:"
journalctl -u "$SERVICE" -n 60 --no-pager | grep -iE 'error|exception|traceback|timeout|killed|denied' | tail -25
exit 1
