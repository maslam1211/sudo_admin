"""SudoTag background worker: periodic jobs + outbox.

    python manage.py run_worker          # run until stopped (systemd)
    python manage.py run_worker --once   # one pass (testing / cron)
"""

from __future__ import annotations

import logging
import signal
import threading

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from api import worker

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Run SudoTag periodic jobs and outbox events.'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true')
        parser.add_argument('--interval', type=float, default=5.0, help='Seconds between passes.')

    def handle(self, *args, once=False, interval=5.0, **opts):
        stop = threading.Event()
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda *_: stop.set())
        self.stdout.write('SudoTag worker started.')
        while not stop.is_set():
            close_old_connections()
            try:
                ran = worker.run_due_jobs()
                outbox = worker.process_outbox()
                if ran or any(outbox.values()):
                    logger.info('worker pass: jobs=%s outbox=%s', ran, outbox)
            except Exception:
                logger.exception('worker pass failed')
            if once:
                break
            stop.wait(interval)
        self.stdout.write('SudoTag worker stopped.')
