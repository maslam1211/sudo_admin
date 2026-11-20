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

# nginx rejects bodies over 1 MB by default (HTTP 413), which blocks ad image
# uploads. Match Django's 50 MB limit (DATA_UPLOAD_MAX_MEMORY_SIZE).
echo "== nginx upload limit"
UPLOAD_CONF=/etc/nginx/conf.d/sudotag-upload-size.conf
echo "client_max_body_size 50m;" > "$UPLOAD_CONF"
# A smaller limit inside the sudotag.com server block would override the global one.
for f in $(grep -rlE 'server_name[^;]*sudotag\.com' /etc/nginx/sites-enabled/ /etc/nginx/conf.d/ 2>/dev/null || true); do
  real="$(readlink -f "$f")"
  if grep -qE '^[[:space:]]*client_max_body_size' "$real"; then
    sed -i -E 's/^([[:space:]]*)client_max_body_size[^;]*;/\1client_max_body_size 50m;/' "$real"
    echo "set client_max_body_size 50m in $real"
  fi
done
if nginx -t 2>/dev/null; then
  systemctl reload nginx && echo "nginx allows 50 MB uploads"
else
  rm -f "$UPLOAD_CONF"
  nginx -t || true
  echo "nginx config test failed; upload limit not changed"
fi

for i in $(seq 1 30); do
  CODE="$(curl -s -o /dev/null -w '%{http_code}' https://sudotag.com/admin/login/ || true)"
  case "$CODE" in 200|301|302) echo "live: HTTP $CODE  ($(git log --oneline -1))"; exit 0;; esac
  sleep 2
done
echo "site not answering (HTTP $CODE). Last errors:"
journalctl -u "$SERVICE" -n 60 --no-pager | grep -iE 'error|exception|traceback|timeout|killed|denied' | tail -25
exit 1
