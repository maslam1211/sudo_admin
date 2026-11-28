"""Background work for the SudoTag server: periodic jobs and the outbox.

Run one process with `python manage.py run_worker` (systemd unit in
deploy/sudotag-worker.service). Jobs hold a lease in worker_scheduled_job,
so a second worker, or a restart mid-run, never runs the same job twice at
the same time.

Outbox: code that changes data calls `enqueue(topic, payload)` in the same
transaction; the worker runs the handler registered with `@handler(topic)`
and retries with exponential backoff. This replaces Firestore triggers as
domains move to PostgreSQL (Phase 2).
"""

from __future__ import annotations

import logging
import traceback
from dataclasses import dataclass
from datetime import timedelta
from typing import Callable

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import OutboxEvent, RateLimitBucket, ScheduledJob

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 8
OUTBOX_LEASE = timedelta(minutes=5)


# ─── periodic jobs ───────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Job:
    name: str
    every: timedelta
    run: Callable[[], object]
    lease: timedelta = timedelta(minutes=30)
    enabled: Callable[[], bool] = lambda: True


def _scheduled_push():
    from admin_app.scheduled_push import run_due_schedules

    from . import firebase

    return run_due_schedules(firebase.firestore_db())


def _cleanup_orphan_documents():
    from django.core.management import call_command

    call_command('cleanup_orphan_documents', '--apply')


def _mirror_firebase():
    from .management.commands.mirror_firebase import default_sources
    from .mirror import run_full_mirror

    return run_full_mirror(**default_sources()).status


def _prune():
    now = timezone.now()
    RateLimitBucket.objects.filter(window_start__lt=now - timedelta(days=2)).delete()
    OutboxEvent.objects.filter(status=OutboxEvent.STATUS_DONE, processed_at__lt=now - timedelta(days=30)).delete()


def _sync_phase2():
    """Firestore -> PostgreSQL for records old writers still master, and
    retry any order copy to Firestore that failed."""
    from appconfig import service as appconfig_service
    from commerce import sync as commerce_sync

    from . import firebase

    db = firebase.firestore_db()
    return {'commerce': commerce_sync.import_everything(db), 'appconfig': appconfig_service.import_everything(db)}


def _sync_referrals():
    """Codes and referrals the Cloud Function triggers (new user, first
    vehicle) and older builds wrote. Reads every users doc, so it runs every
    10 minutes, not 2; API writes are copied at once."""
    from referrals import service as referral_service

    from . import firebase

    return referral_service.import_everything(firebase.firestore_db())


def _sync_partners():
    """Read copy of the Partner Programme; the Cloud Functions still own every
    balance change (their triggers run after admin decisions and orders)."""
    from partners import sync as partner_sync

    from . import firebase

    return partner_sync.import_everything(firebase.firestore_db())


def _sync_civic():
    """Read copy of CivicSense; reports are still written by the Cloud
    Functions and the admin panel in Firestore."""
    from civic import sync as civic_sync

    from . import firebase

    return civic_sync.import_everything(firebase.firestore_db())


def _sync_accounts():
    """User profiles, settings, every user subcollection, blocks, family, usage."""
    from accounts import sync as accounts_sync

    from . import firebase

    return accounts_sync.import_everything(firebase.firestore_db())


def _mirror_hours() -> float:
    return float(getattr(settings, 'MIRROR_INTERVAL_HOURS', 24) or 0)


JOBS: list[Job] = [
    Job('heartbeat', timedelta(minutes=1), lambda: None, lease=timedelta(minutes=1)),
    # Only when the old in-web thread is off (SCHEDULED_PUSH_IN_WEB=0), so a
    # schedule is never sent twice.
    Job('scheduled_push', timedelta(minutes=1), _scheduled_push, lease=timedelta(minutes=5),
        enabled=lambda: not getattr(settings, 'SCHEDULED_PUSH_IN_WEB', True)),
    Job('cleanup_orphan_documents', timedelta(days=1), _cleanup_orphan_documents),
    Job('mirror_firebase', timedelta(hours=24), _mirror_firebase, lease=timedelta(hours=2),
        enabled=lambda: _mirror_hours() > 0),
    Job('prune', timedelta(days=1), _prune),
    Job('sync_phase2', timedelta(minutes=2), _sync_phase2, lease=timedelta(minutes=10)),
    Job('sync_referrals', timedelta(minutes=10), _sync_referrals, lease=timedelta(minutes=10)),
    Job('sync_partners', timedelta(minutes=5), _sync_partners, lease=timedelta(minutes=10)),
    Job('sync_civic', timedelta(minutes=10), _sync_civic, lease=timedelta(minutes=10)),
    Job('sync_accounts', timedelta(minutes=10), _sync_accounts, lease=timedelta(minutes=10)),
]


def _interval(job: Job) -> timedelta:
    if job.name == 'mirror_firebase' and _mirror_hours() > 0:
        return timedelta(hours=_mirror_hours())
    return job.every


def _claim(job: Job, now) -> bool:
    ScheduledJob.objects.get_or_create(name=job.name, defaults={'next_run_at': now})
    with transaction.atomic():
        row = ScheduledJob.objects.select_for_update(skip_locked=True).filter(name=job.name).first()
        if row is None or row.next_run_at > now:
            return False
        if row.lease_until is not None and row.lease_until > now:
            return False
        row.lease_until = now + job.lease
        row.last_started_at = now
        row.save(update_fields=['lease_until', 'last_started_at'])
    return True


def run_job(job: Job, now=None) -> bool:
    """Run `job` if due and not leased elsewhere. Returns True if it ran."""
    now = now or timezone.now()
    if not job.enabled() or not _claim(job, now):
        return False
    status, error = 'ok', ''
    try:
        job.run()
    except Exception as exc:
        status, error = 'failed', f'{type(exc).__name__}: {exc}\n{traceback.format_exc()[-3000:]}'
        logger.exception('worker job %s failed', job.name)
    ScheduledJob.objects.filter(name=job.name).update(
        lease_until=None, last_finished_at=timezone.now(), last_status=status, last_error=error,
        next_run_at=now + _interval(job), run_count=F('run_count') + 1,
    )
    return True


def run_due_jobs(now=None) -> list[str]:
    return [job.name for job in JOBS if run_job(job, now)]


# ─── outbox ──────────────────────────────────────────────────────────────────
HANDLERS: dict[str, Callable[[dict], None]] = {}


def handler(topic: str):
    def register(fn):
        HANDLERS[topic] = fn
        return fn
    return register


def enqueue(topic: str, payload: dict | None = None, *, delay: timedelta | None = None) -> OutboxEvent:
    """Queue work. Call inside the transaction that made the change."""
    return OutboxEvent.objects.create(
        topic=topic, payload=payload or {},
        available_at=timezone.now() + (delay or timedelta(0)),
    )


def _backoff(attempts: int) -> timedelta:
    return min(timedelta(minutes=2 ** attempts), timedelta(hours=6))


def process_outbox(batch: int = 20, now=None) -> dict:
    now = now or timezone.now()
    with transaction.atomic():
        claimed = list(
            OutboxEvent.objects.select_for_update(skip_locked=True)
            .filter(status=OutboxEvent.STATUS_PENDING, available_at__lte=now)
            .order_by('id')[:batch]
        )
        for event in claimed:
            event.attempts += 1
            event.available_at = now + OUTBOX_LEASE  # hidden from other workers while running
            event.save(update_fields=['attempts', 'available_at'])

    stats = {'done': 0, 'retry': 0, 'dead': 0}
    for event in claimed:
        fn = HANDLERS.get(event.topic)
        try:
            if fn is None:
                raise LookupError(f'no handler for topic {event.topic!r}')
            fn(event.payload)
        except Exception as exc:
            error = f'{type(exc).__name__}: {exc}'[:2000]
            if event.attempts >= MAX_ATTEMPTS or fn is None:
                event.status = OutboxEvent.STATUS_DEAD
                stats['dead'] += 1
                logger.error('outbox event %s (%s) dead: %s', event.pk, event.topic, error)
            else:
                event.available_at = timezone.now() + _backoff(event.attempts)
                stats['retry'] += 1
            event.last_error = error
            event.save(update_fields=['status', 'available_at', 'last_error'])
            continue
        event.status = OutboxEvent.STATUS_DONE
        event.processed_at = timezone.now()
        event.last_error = ''
        event.save(update_fields=['status', 'processed_at', 'last_error'])
        stats['done'] += 1
    return stats


def worker_status() -> dict:
    """Liveness for /api/v1/health: when the heartbeat job last finished."""
    beat = ScheduledJob.objects.filter(name='heartbeat').values_list('last_finished_at', flat=True).first()
    if beat is None:
        return {'state': 'not-started'}
    age = (timezone.now() - beat).total_seconds()
    return {'state': 'ok' if age < 300 else 'stale', 'lastHeartbeatSecondsAgo': int(age)}
