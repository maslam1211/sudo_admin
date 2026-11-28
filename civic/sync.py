"""Copy CivicSense data Firestore -> PostgreSQL (read-only on Firestore)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from django.db import models as dj_models
from django.utils import timezone as dj_tz

from api.mirror import decode, encode

from .models import (
    CivicAdminLog, CivicCampaign, CivicImport, CivicLeaderboardEntry, CivicOwnerAlert, CivicPoints,
    CivicPointsLedgerEntry, CivicRateLimit, CivicReport, CivicReportAction, CivicReportPrivate, CivicStat,
    CivicVehiclePush,
)

logger = logging.getLogger(__name__)


def _int(value) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return 0


def _dt(value):
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return None


def _s(value, n) -> str:
    return str(value or '')[:n]


@dataclass(frozen=True)
class Table:
    collection: str
    model: type[dj_models.Model]
    columns: Callable[[dict], dict]


TABLES = [
    Table('civic_reports', CivicReport,
          lambda d: {'reporter_uid': _s(d.get('reporterUid'), 128), 'status': _s(d.get('status'), 20),
                     'category': _s(d.get('category'), 32), 'created_at': _dt(d.get('createdAt'))}),
    Table('civic_reports_private', CivicReportPrivate,
          lambda d: {'owner_uid': _s(d.get('ownerUid'), 128), 'match_status': _s(d.get('matchStatus'), 32),
                     'created_at': _dt(d.get('createdAt'))}),
    Table('civic_owner_alerts', CivicOwnerAlert,
          lambda d: {'owner_uid': _s(d.get('ownerUid'), 128), 'owner_status': _s(d.get('ownerStatus'), 20),
                     'created_at': _dt(d.get('reportedAt'))}),
    Table('civic_report_actions', CivicReportAction,
          lambda d: {'report_doc_id': _s(d.get('reportDocId'), 128), 'at': _dt(d.get('at'))}),
    Table('civic_admin_logs', CivicAdminLog,
          lambda d: {'report_doc_id': _s(d.get('reportDocId'), 128), 'at': _dt(d.get('at'))}),
    Table('civic_awareness', CivicCampaign,
          lambda d: {'is_active': d.get('isActive') is not False, 'publish_at': _dt(d.get('publishAt'))}),
    Table('civic_stats', CivicStat, lambda d: {}),
    Table('civic_points', CivicPoints, lambda d: {'total': _int(d.get('total'))}),
    Table('civic_leaderboard', CivicLeaderboardEntry,
          lambda d: {'month_key': _s(d.get('monthKey'), 8), 'month_points': _int(d.get('monthPoints'))}),
    Table('civic_rate_limits', CivicRateLimit, lambda d: {}),
    Table('civic_vehicle_push', CivicVehiclePush, lambda d: {}),
]
TABLE = {t.collection: t for t in TABLES}


def _ledger_cols(uid: str, d: dict) -> dict:
    return {'uid': uid, 'reason': _s(d.get('reason'), 40), 'points': _int(d.get('points')), 'at': _dt(d.get('at'))}


def _upsert(model, doc_id: str, data: dict, columns: dict) -> None:
    model.objects.update_or_create(id=doc_id, defaults={
        **columns, 'document': encode(data), 'synced_at': dj_tz.now(), 'deleted_at': None})


def _mark_gone(qs, seen) -> int:
    return qs.filter(deleted_at__isnull=True).exclude(pk__in=seen).update(deleted_at=dj_tz.now())


def import_doc(db, collection: str, doc_id: str) -> None:
    table = TABLE[collection]
    snap = db.collection(collection).document(doc_id).get()
    if snap.exists:
        data = snap.to_dict() or {}
        _upsert(table.model, doc_id, data, table.columns(data))
    else:
        table.model.objects.filter(pk=doc_id, deleted_at__isnull=True).update(deleted_at=dj_tz.now())


def import_ledger(db, uid: str) -> None:
    seen = []
    for entry in db.collection('civic_points').document(uid).collection('ledger').stream():
        data = entry.to_dict() or {}
        entry_id = f'{uid}/{entry.id}'
        seen.append(entry_id)
        _upsert(CivicPointsLedgerEntry, entry_id, data, _ledger_cols(uid, data))
    _mark_gone(CivicPointsLedgerEntry.objects.filter(uid=uid), seen)


def import_everything(db) -> dict:
    stats = {}
    for table in TABLES:
        seen = []
        for snap in db.collection(table.collection).stream():
            data = snap.to_dict() or {}
            seen.append(snap.id)
            _upsert(table.model, snap.id, data, table.columns(data))
        stats[table.collection] = {'imported': len(seen), 'marked_deleted': _mark_gone(table.model.objects, seen)}
    uids = list(CivicPoints.objects.filter(deleted_at__isnull=True).values_list('id', flat=True))
    for uid in uids:
        import_ledger(db, uid)
    _mark_gone(CivicPointsLedgerEntry.objects.exclude(uid__in=uids), [])
    stats['ledger_entries'] = CivicPointsLedgerEntry.objects.filter(deleted_at__isnull=True).count()
    CivicImport.objects.update_or_create(id='full', defaults={'finished_at': dj_tz.now()})
    return stats


def _by_report(db, collection: str, report_doc_id: str) -> None:
    for snap in db.collection(collection).where('reportDocId', '==', report_doc_id).stream():
        data = snap.to_dict() or {}
        _upsert(TABLE[collection].model, snap.id, data, TABLE[collection].columns(data))


def refresh_report(db, report_doc_id: str) -> None:
    """After an admin write on a report: the report, its private record and
    owner alert, its logs, the reporter's points and the public stats."""
    import_doc(db, 'civic_reports', report_doc_id)
    import_doc(db, 'civic_reports_private', report_doc_id)
    private = CivicReportPrivate.objects.filter(pk=report_doc_id).first()
    alert_id = decode(private.document).get('alertId') if private else None
    if alert_id:
        import_doc(db, 'civic_owner_alerts', str(alert_id))
    _by_report(db, 'civic_report_actions', report_doc_id)
    _by_report(db, 'civic_admin_logs', report_doc_id)
    report = CivicReport.objects.filter(pk=report_doc_id).first()
    if report and report.reporter_uid:
        refresh_member(db, report.reporter_uid)
    import_doc(db, 'civic_stats', 'global')


def refresh_member(db, uid: str) -> None:
    import_doc(db, 'civic_points', uid)
    import_ledger(db, uid)
    points = CivicPoints.objects.filter(pk=uid).first()
    board_id = decode(points.document).get('leaderboardId') if points else None
    if board_id:
        import_doc(db, 'civic_leaderboard', str(board_id))


def refresh_campaign(db, campaign_id: str) -> None:
    import_doc(db, 'civic_awareness', campaign_id)
    import_doc(db, 'civic_stats', 'global')


def postgres_ready() -> bool:
    try:
        return CivicImport.objects.filter(id='full').exists()
    except Exception:  # tables missing before migrate
        return False


class Doc:
    """Looks like a Firestore snapshot, so admin normalizers work on PostgreSQL rows."""

    def __init__(self, doc_id: str, document):
        self.id = doc_id
        self._data = decode(document)
        self.exists = True

    def to_dict(self):
        return dict(self._data)
