#!/usr/bin/env bash
# Install and start the SudoTag background worker (python manage.py run_worker)
# as a systemd service next to the existing gunicorn service. It uses the same
# user, project folder, virtualenv and /etc/sudotag/sudotag.env as gunicorn.
#
#   sudo -E bash deploy/install_worker.sh            # SERVICE=<gunicorn unit> to choose
#
# After it is running, set SCHEDULED_PUSH_IN_WEB=0 in /etc/sudotag/sudotag.env
# and restart gunicorn, so scheduled pushes are sent only by the worker.
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE=/etc/sudotag/sudotag.env
UNIT=/etc/systemd/system/sudotag-worker.service

SERVICE="${SERVICE:-$(systemctl list-unit-files --type=service --no-legend | awk '{print $1}' | grep -iE 'gunicorn|sudo' | grep -v sudotag-worker | head -1)}"
[ -n "$SERVICE" ] || { echo "No gunicorn service found; run with SERVICE=name.service" >&2; exit 1; }
RUN_USER="$(systemctl show -p User --value "$SERVICE")"; RUN_USER="${RUN_USER:-www-data}"
WORKDIR="$(systemctl show -p WorkingDirectory --value "$SERVICE")"; WORKDIR="${WORKDIR:-$PROJECT_DIR}"
PY=python3
for v in venv .venv env; do [ -x "$WORKDIR/$v/bin/python" ] && PY="$WORKDIR/$v/bin/python" && break; done

cat > "$UNIT" <<UNITEOF
[Unit]
Description=SudoTag background worker (jobs, outbox, Firebase mirror)
After=network-online.target postgresql.service
Wants=network-online.target

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$WORKDIR
EnvironmentFile=-$ENV_FILE
Environment=PYTHONUNBUFFERED=1
ExecStart=$PY manage.py run_worker
Restart=always
RestartSec=5
KillSignal=SIGTERM
TimeoutStopSec=60

[Install]
WantedBy=multi-user.target
UNITEOF

systemctl daemon-reload
systemctl enable --now sudotag-worker
systemctl --no-pager status sudotag-worker | head -5
echo "Worker installed ($UNIT) as $RUN_USER in $WORKDIR using $PY."
echo "Next: set SCHEDULED_PUSH_IN_WEB=0 in $ENV_FILE and restart $SERVICE."
