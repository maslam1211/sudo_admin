"""Copy Partner Programme data Firestore -> PostgreSQL (read-only on Firestore)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from django.db import models as dj_models
from django.utils import timezone as dj_tz

from api.mirror import decode, encode

from .models import (
    Partner, PartnerActivationClaim, PartnerAdminAudit, PartnerCode, PartnerCommission, PartnerImport,
    PartnerLedgerEntry, PartnerPayout, PartnerSetting, PartnerWithdrawal,
)

logger = logging.getLogger(__name__)

SETTING_PATHS = ('partnerProgram/config', 'counters/partnerIds')


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


def _partner_cols(d: dict) -> dict:
    w = d.get('wallet') if isinstance(d.get('wallet'), dict) else {}
    return {'partner_id': _s(d.get('partnerId'), 32), 'name': _s(d.get('name'), 200),
            'phone': _s(d.get('phone'), 40), 'city': _s(d.get('city'), 100), 'status': _s(d.get('status'), 16),
            'wallet_available': _int(w.get('available')), 'wallet_pending': _int(w.get('pending')),
            'wallet_on_hold': _int(w.get('onHold')), 'wallet_paid': _int(w.get('paid')),
            'wallet_lifetime': _int(w.get('lifetime')), 'applied_at': _dt(d.get('appliedAt'))}


@dataclass(frozen=True)
class Table:
    collection: str
    model: type[dj_models.Model]
    key: str
    columns: Callable[[dict], dict]


TABLES = [
    Table('partners', Partner, 'uid', _partner_cols),
    Table('partnerCodes', PartnerCode, 'code',
          lambda d: {'partner_uid': _s(d.get('uid'), 128), 'active': d.get('active') is True}),
    Table('partnerCommissions', PartnerCommission, 'id',
          lambda d: {'partner_uid': _s(d.get('partnerUid'), 128), 'status': _s(d.get('status'), 16),
                     'amount': _int(d.get('amount')), 'quantity': _int(d.get('quantity')),
                     'source': _s(d.get('source'), 32), 'created_at': _dt(d.get('createdAt')),
                     'available_at': _dt(d.get('availableAt'))}),
    Table('partnerWithdrawals', PartnerWithdrawal, 'id',
          lambda d: {'partner_uid': _s(d.get('partnerUid'), 128), 'status': _s(d.get('status'), 16),
                     'amount': _int(d.get('amount')), 'requested_at': _dt(d.get('requestedAt'))}),
    Table('partnerActivationClaims', PartnerActivationClaim, 'id',
          lambda d: {'partner_uid': _s(d.get('partnerUid'), 128), 'status': _s(d.get('status'), 16)}),
    Table('partner_admin_audit', PartnerAdminAudit, 'id',
          lambda d: {'kind': _s(d.get('kind'), 32), 'action': _s(d.get('action'), 32), 'at': _dt(d.get('at'))}),
]
TABLE = {t.collection: t for t in TABLES}


def _ledger_cols(uid: str, d: dict) -> dict:
    return {'partner_uid': uid, 'type': _s(d.get('type'), 40), 'amount': _int(d.get('amount')),
            'ref': _s(d.get('ref'), 200), 'created_at': _dt(d.get('createdAt'))}


def _upsert(model, key: str, doc_id: str, data: dict, columns: dict) -> None:
    model.objects.update_or_create(**{key: doc_id}, defaults={
        **columns, 'document': encode(data), 'synced_at': dj_tz.now(), 'deleted_at': None})


def _mark_gone(qs, seen) -> int:
    return qs.filter(deleted_at__isnull=True).exclude(pk__in=seen).update(deleted_at=dj_tz.now())


def store(table: Table, doc_id: str, data: dict) -> None:
    _upsert(table.model, table.key, doc_id, data, table.columns(data))


def import_doc(db, collection: str, doc_id: str) -> None:
    table = TABLE[collection]
    snap = db.collection(collection).document(doc_id).get()
    if snap.exists:
        store(table, doc_id, snap.to_dict() or {})
    else:
        table.model.objects.filter(pk=doc_id, deleted_at__isnull=True).update(deleted_at=dj_tz.now())


def _import_settings(db) -> int:
    for path in SETTING_PATHS:
        coll, doc_id = path.split('/')
        snap = db.collection(coll).document(doc_id).get()
        if snap.exists:
            _upsert(PartnerSetting, 'path', path, snap.to_dict() or {}, {})
        else:
            PartnerSetting.objects.filter(path=path, deleted_at__isnull=True).update(deleted_at=dj_tz.now())
    return len(SETTING_PATHS)


def import_partner_children(db, uid: str) -> None:
    """partners/{uid}/private/payout and the whole ledger of one partner."""
    ref = db.collection('partners').document(uid)
    payout = ref.collection('private').document('payout').get()
    if payout.exists:
        _upsert(PartnerPayout, 'uid', uid, payout.to_dict() or {}, {})
    else:
        PartnerPayout.objects.filter(uid=uid, deleted_at__isnull=True).update(deleted_at=dj_tz.now())
    seen = []
    for entry in ref.collection('ledger').stream():
        data = entry.to_dict() or {}
        entry_id = f'{uid}/{entry.id}'
        seen.append(entry_id)
        _upsert(PartnerLedgerEntry, 'id', entry_id, data, _ledger_cols(uid, data))
    _mark_gone(PartnerLedgerEntry.objects.filter(partner_uid=uid), seen)


def import_everything(db) -> dict:
    stats = {'settings': _import_settings(db)}
    for table in TABLES:
        seen = []
        for snap in db.collection(table.collection).stream():
            seen.append(snap.id)
            store(table, snap.id, snap.to_dict() or {})
        stats[table.collection] = {'imported': len(seen), 'marked_deleted': _mark_gone(table.model.objects, seen)}
    partner_uids = list(Partner.objects.filter(deleted_at__isnull=True).values_list('uid', flat=True))
    for uid in partner_uids:
        import_partner_children(db, uid)
    # Children of partners whose document is gone are kept, marked deleted.
    _mark_gone(PartnerPayout.objects.exclude(uid__in=partner_uids), [])
    _mark_gone(PartnerLedgerEntry.objects.exclude(partner_uid__in=partner_uids), [])
    stats['ledger_entries'] = PartnerLedgerEntry.objects.filter(deleted_at__isnull=True).count()
    PartnerImport.objects.update_or_create(id='full', defaults={'finished_at': dj_tz.now()})
    return stats


def refresh_partner(db, uid: str, *, withdrawal_id: str = '', commission_id: str = '') -> None:
    """After an admin decision: the documents it (and the triggers) touch.
    Never raises — the worker's next full import catches anything missed."""
    try:
        import_doc(db, 'partners', uid)
        import_partner_children(db, uid)
        partner = Partner.objects.filter(uid=uid).first()
        if partner and partner.partner_id:
            import_doc(db, 'partnerCodes', partner.partner_id)
        if withdrawal_id:
            import_doc(db, 'partnerWithdrawals', withdrawal_id)
        if commission_id:
            import_doc(db, 'partnerCommissions', commission_id)
    except Exception:
        logger.exception('partners: refresh of %s failed (worker will retry)', uid)


def refresh_settings(db) -> None:
    try:
        _import_settings(db)
    except Exception:
        logger.exception('partners: settings refresh failed (worker will retry)')


def postgres_ready() -> bool:
    try:
        return PartnerImport.objects.filter(id='full').exists()
    except Exception:  # tables missing before migrate
        return False


class Doc:
    """Looks like a Firestore snapshot, so admin row builders work on PostgreSQL rows."""

    def __init__(self, doc_id: str, document):
        self.id = doc_id
        self._data = decode(document)
        self.exists = True

    def to_dict(self):
        return dict(self._data)
