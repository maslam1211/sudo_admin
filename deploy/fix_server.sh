#!/usr/bin/env bash
# One-time server fix for 502 Bad Gateway (run on the VPS as root):
#     sudo bash deploy/fix_server.sh
#
# Makes the gunicorn service (not a hand-started process) run the app, gives it
# the settings in /etc/sudotag/sudotag.env, lets it start slowly, restarts it if
# it crashes, and checks the app really answers. Safe to run again.
set -euo pipefail

ENV_FILE=/etc/sudotag/sudotag.env
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

say()  { printf '\n== %s\n' "$*"; }
fail() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || fail "run as root: sudo bash deploy/fix_server.sh"

say "1. Find the gunicorn service"
SERVICE="${SERVICE:-$(systemctl list-unit-files --type=service --no-legend 2>/dev/null \
  | awk '{print $1}' | grep -iE 'gunicorn|sudo' | head -1)}"
[ -n "$SERVICE" ] || fail "no gunicorn service found. Run: systemctl list-unit-files | grep -i gunicorn, then SERVICE=name.service sudo -E bash $0"
echo "service: $SERVICE"
EXEC="$(systemctl show -p ExecStart --value "$SERVICE")"
RUN_USER="$(systemctl show -p User --value "$SERVICE")"; RUN_USER="${RUN_USER:-root}"
echo "runs as: $RUN_USER"

say "2. Stop gunicorn processes started by hand (they die when SSH closes)"
CGROUP="$(systemctl show -p ControlGroup --value "$SERVICE")"
for pid in $(pgrep -f 'gunicorn|manage.py runserver' || true); do
  [ "$pid" = "$$" ] && continue
  # Processes inside the service's cgroup belong to systemd: leave them.
  if [ -n "$CGROUP" ] && grep -qF "$CGROUP" "/proc/$pid/cgroup" 2>/dev/null; then
    continue
  fi
  echo "stopping hand-started process $pid: $(ps -o args= -p "$pid" | cut -c1-80)"
  kill "$pid" 2>/dev/null || true
done

say "3. Check the settings file"
[ -f "$ENV_FILE" ] || fail "$ENV_FILE is missing. Copy sudotag.env there first."
grep -q '^DJANGO_SECRET_KEY=.\+' "$ENV_FILE" || fail "DJANGO_SECRET_KEY is empty in $ENV_FILE"
KEY_PATH="$(grep -E '^GOOGLE_APPLICATION_CREDENTIALS=' "$ENV_FILE" | tail -1 | cut -d= -f2-)"
[ -n "$KEY_PATH" ] || fail "GOOGLE_APPLICATION_CREDENTIALS is not set in $ENV_FILE"
[ -f "$KEY_PATH" ] || fail "Firebase key not found at $KEY_PATH"
if [[ "$KEY_PATH" == /root/* && "$RUN_USER" != root ]]; then
  NEW_KEY=/etc/sudotag/firebase-key.json
  echo "$RUN_USER cannot read /root: moving the key to $NEW_KEY"
  install -m 600 "$KEY_PATH" "$NEW_KEY"
  sed -i "s#^GOOGLE_APPLICATION_CREDENTIALS=.*#GOOGLE_APPLICATION_CREDENTIALS=$NEW_KEY#" "$ENV_FILE"
  KEY_PATH="$NEW_KEY"
fi
chown "$RUN_USER" "$ENV_FILE" "$KEY_PATH"
chmod 600 "$ENV_FILE" "$KEY_PATH"
chmod 755 /etc/sudotag
echo "settings and key readable by $RUN_USER"

say "4. Check the code reads $ENV_FILE"
grep -q "sudotag/sudotag.env" "$PROJECT_DIR/sudo_admin/settings.py" \
  || fail "code is too old. In $PROJECT_DIR run: git pull   (need commit c97eb68 or later)"
echo "code: $(git -C "$PROJECT_DIR" log --oneline -1 2>/dev/null || echo unknown)"

say "5. Service settings: env file, longer start timeout, auto-restart"
mkdir -p "/etc/systemd/system/$SERVICE.d"
cat > "/etc/systemd/system/$SERVICE.d/sudotag.conf" <<CONF
[Service]
EnvironmentFile=-$ENV_FILE
# Firebase connects at startup; the default 30s worker timeout can kill it.
Environment="GUNICORN_CMD_ARGS=--timeout 120 --graceful-timeout 30"
Restart=always
RestartSec=3
CONF
systemctl daemon-reload
systemctl enable "$SERVICE" >/dev/null 2>&1 || true

say "6. Restart"
systemctl restart "$SERVICE"

say "7. Check the app answers"
BIND="$(grep -oE -- '(--bind|-b)[ =][^ ;]+' <<<"$EXEC" | head -1 | sed -E 's/^(--bind|-b)[ =]//')"
BIND="${BIND:-127.0.0.1:8000}"
echo "gunicorn listens on: $BIND"
for i in $(seq 1 30); do
  if [[ "$BIND" == unix:* ]]; then
    CODE="$(curl -s -o /dev/null -w '%{http_code}' --unix-socket "${BIND#unix:}" http://localhost/admin/login/ || true)"
  else
    CODE="$(curl -s -o /dev/null -w '%{http_code}' "http://$BIND/admin/login/" || true)"
  fi
  case "$CODE" in 200|301|302) echo "app answers: HTTP $CODE"; break;; esac
  sleep 2
done
case "${CODE:-000}" in
  200|301|302) ;;
  *) echo "app did not answer (last: ${CODE:-none}). Last errors:"
     journalctl -u "$SERVICE" -n 60 --no-pager | grep -iE 'error|exception|traceback|timeout|killed|denied|No such' | tail -25
     fail "send the lines above to fix the rest";;
esac

say "8. Static files (logo, CSS)"
PY=python3
for v in venv .venv env; do [ -x "$PROJECT_DIR/$v/bin/python" ] && PY="$PROJECT_DIR/$v/bin/python" && break; done
(cd "$PROJECT_DIR" && set -a && . "$ENV_FILE" && set +a && "$PY" manage.py collectstatic --noinput >/dev/null) \
  && echo "collectstatic done" || echo "collectstatic failed (site still works; logo may 404)"

say "9. Make nginx forward to where gunicorn listens"
if [[ "$BIND" == unix:* ]]; then
  WANT="http://unix:${BIND#unix:}"
  SOCK="${BIND#unix:}"
  # nginx (www-data) must be able to open the socket.
  if [ -S "$SOCK" ] && ! sudo -u www-data test -w "$SOCK" 2>/dev/null; then
    echo "nginx cannot open $SOCK: adding www-data to $RUN_USER's group and opening the socket to the group"
    usermod -a -G "$(id -gn "$RUN_USER")" www-data || true
    sed -i 's#^Environment="GUNICORN_CMD_ARGS=\(.*\)"#Environment="GUNICORN_CMD_ARGS=\1 --umask 007"#' \
      "/etc/systemd/system/$SERVICE.d/sudotag.conf"
    systemctl daemon-reload && systemctl restart "$SERVICE" && sleep 5
    systemctl restart nginx
  fi
else
  WANT="http://$BIND"
fi
echo "gunicorn: $WANT"
CONF_FILES="$(grep -rlE 'server_name[^;]*sudotag\.com' /etc/nginx/sites-enabled/ /etc/nginx/conf.d/ 2>/dev/null || true)"
[ -n "$CONF_FILES" ] || echo "no nginx site for sudotag.com found in sites-enabled/conf.d"
for f in $CONF_FILES; do
  real="$(readlink -f "$f")"
  while read -r target; do
    [ -z "$target" ] && continue
    norm="${target%/}"
    if [ "$norm" != "$WANT" ]; then
      echo "$real forwards to $target, but gunicorn is on $WANT: fixing"
      cp -n "$real" "$real.bak-$(date +%Y%m%d%H%M%S)"
      sed -i "s#proxy_pass[[:space:]]\+$target#proxy_pass $WANT#g" "$real"
    else
      echo "$real forwards to $target: OK"
    fi
  done < <(grep -oE 'proxy_pass[[:space:]]+[^;]+' "$real" | awk '{print $2}' | sort -u)
done
if nginx -t 2>/dev/null; then
  systemctl reload nginx && echo "nginx reloaded"
else
  nginx -t || true
  fail "nginx config test failed: restore the .bak file shown above and send me the output"
fi

say "10. Through nginx"
sleep 2
LIVE="$(curl -s -o /dev/null -w '%{http_code}' https://sudotag.com/admin/login/ || true)"
echo "https://sudotag.com/admin/login/ -> HTTP $LIVE"
case "$LIVE" in
  200|301|302) echo "Done: the site is up. Future deploys: sudo bash deploy/deploy.sh";;
  *) echo "Still failing. nginx says:"
     tail -8 /var/log/nginx/error.log 2>/dev/null || true
     fail "send the lines above";;
esac
