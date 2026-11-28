"""SudoTag Partner Programme — admin side.

The admin panel only records *decisions* (approve a partner, mark a
withdrawal paid with its UTR, reverse a commission, edit settings). The
Cloud Functions in the app repo (functions/partner_programme.js) turn those
decisions into wallet and ledger changes, exactly once. This module never
writes a wallet balance.

Firestore: partners/{uid}, partners/{uid}/private/payout,
partners/{uid}/ledger, partnerCommissions/{orderId},
partnerWithdrawals/{id}, partnerProgram/config.
"""
from __future__ import annotations

import re
from typing import Any

from firebase_admin import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

DEFAULT_CONFIG = {
    'enabled': True,
    'commissionPerTag': 111,
    'holdDays': 7,
    'minWithdrawal': 500,
    'targetDays': None,
    'targets': [
        {'key': 'starter', 'name': 'Starter', 'tags': 10, 'bonus': 1250},
        {'key': 'growth', 'name': 'Growth', 'tags': 50, 'bonus': 7500},
        {'key': 'premium', 'name': 'Premium', 'tags': 100, 'bonus': 20000},
    ],
}

PARTNER_STATUSES = ('pending', 'approved', 'rejected', 'suspended')
WITHDRAWAL_STATUSES = ('requested', 'paid', 'rejected')
COMMISSION_STATUSES = ('pending', 'approved', 'available', 'reversed')

UTR_RE = re.compile(r'^[A-Za-z0-9-]{6,40}$')


class PartnerAdminError(ValueError):
    """A decision the admin can fix (shown as a flash message)."""


def _db():
    return firestore.client()


def _copy(db):
    """partners.sync when reading the PostgreSQL copy: only for the real pages
    (no db passed in) and after the first full import."""
    if db is not None:
        return None
    try:
        from partners import sync

        return sync if sync.postgres_ready() else None
    except Exception:
        return None


def _refresh(db_given, fn, *args, **kwargs):
    """Copy what a decision changed into PostgreSQL (real pages only)."""
    if db_given is not None:
        return
    try:
        from partners import sync

        getattr(sync, fn)(_db(), *args, **kwargs)
    except Exception:
        pass  # the worker's next import catches it


def _copied_rows(model, row_fn, limit, order, **filters):
    from partners.sync import Doc

    qs = model.objects.filter(deleted_at__isnull=True, **filters).order_by(*order)[:limit]
    return [row_fn(Doc(r.pk, r.document)) for r in qs]


def stamp(value) -> str:
    if value is None:
        return ''
    fmt = getattr(value, 'strftime', None)
    if callable(fmt):
        return value.strftime('%d %b %Y, %H:%M')
    return str(value)


def _int(v, default=0) -> int:
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return default


# ─── Settings ───────────────────────────────────────────────────────────────

def load_config(db=None) -> dict:
    db = db or _db()
    snap = db.collection('partnerProgram').document('config').get()
    data = snap.to_dict() if snap.exists else {}
    cfg = {**DEFAULT_CONFIG, **(data or {})}
    if not cfg.get('targets'):
        cfg['targets'] = DEFAULT_CONFIG['targets']
    return cfg


def parse_config_form(form) -> dict:
    """Validate the settings form into a config dict (raises PartnerAdminError)."""
    commission = _int(form.get('commissionPerTag'), -1)
    hold = _int(form.get('holdDays'), -1)
    minimum = _int(form.get('minWithdrawal'), -1)
    if not 1 <= commission <= 10000:
        raise PartnerAdminError('Commission per tag must be between ₹1 and ₹10,000.')
    if not 0 <= hold <= 90:
        raise PartnerAdminError('Hold period must be between 0 and 90 days.')
    if not 1 <= minimum <= 100000:
        raise PartnerAdminError('Minimum withdrawal must be between ₹1 and ₹1,00,000.')
    target_days_raw = (form.get('targetDays') or '').strip()
    target_days = None
    if target_days_raw:
        target_days = _int(target_days_raw, -1)
        if not 1 <= target_days <= 730:
            raise PartnerAdminError('Target period must be 1–730 days, or empty for no limit.')

    targets = []
    for key in ('starter', 'growth', 'premium'):
        tags = _int(form.get(f'{key}_tags'), -1)
        bonus = _int(form.get(f'{key}_bonus'), -1)
        name = (form.get(f'{key}_name') or key.title()).strip()[:30] or key.title()
        if tags < 1 or bonus < 0:
            raise PartnerAdminError(f'{name}: tags must be at least 1 and bonus 0 or more.')
        targets.append({'key': key, 'name': name, 'tags': tags, 'bonus': bonus})
    if len({t['tags'] for t in targets}) != len(targets):
        raise PartnerAdminError('Each target needs a different number of tags.')
    targets.sort(key=lambda t: t['tags'])
    return {
        'enabled': form.get('enabled') in ('on', 'true', '1', True),
        'commissionPerTag': commission,
        'holdDays': hold,
        'minWithdrawal': minimum,
        'targetDays': target_days,
        'targets': targets,
    }


def save_config(config: dict, actor: str, db=None) -> None:
    given = db
    db = db or _db()
    db.collection('partnerProgram').document('config').set({
        **config,
        'updatedBy': actor,
        'updatedAt': firestore.SERVER_TIMESTAMP,
    }, merge=True)
    _refresh(given, 'refresh_settings')


# ─── Reads ──────────────────────────────────────────────────────────────────

def _partner_row(doc) -> dict:
    d = doc.to_dict() or {}
    wallet = d.get('wallet') or {}
    stats = d.get('stats') or {}
    target = d.get('target') or {}
    return {
        'uid': doc.id,
        'partner_id': d.get('partnerId') or '',
        'name': d.get('name') or '',
        'phone': d.get('phone') or '',
        'city': d.get('city') or '',
        'status': d.get('status') or '',
        'applied': stamp(d.get('appliedAt')),
        'approved': stamp(d.get('approvedAt')),
        'reject_reason': d.get('rejectReason') or '',
        'payout_ready': bool(d.get('payoutReady')),
        'payout_display': d.get('payoutDisplay') or '',
        'available': _int(wallet.get('available')),
        'pending': _int(wallet.get('pending')),
        'on_hold': _int(wallet.get('onHold')),
        'paid': _int(wallet.get('paid')),
        'lifetime': _int(wallet.get('lifetime')),
        'verified_tags': _int(stats.get('verifiedTags')),
        'pending_tags': _int(stats.get('pendingTags')),
        'orders': _int(stats.get('referredOrders')),
        'target': (f"{target.get('name')} {target.get('progress', 0)}/{target.get('tags')} ({target.get('status')})"
                   if target else ''),
        'completed_targets': ', '.join(d.get('completedTargets') or []),
    }


def list_partners(status: str = '', query: str = '', db=None, limit: int = 200) -> list[dict]:
    if _copy(db):
        from partners.models import Partner

        rows = _copied_rows(Partner, _partner_row, limit, ['uid'],
                            **({'status': status} if status in PARTNER_STATUSES else {}))
    else:
        db = db or _db()
        ref = db.collection('partners')
        if status in PARTNER_STATUSES:
            ref = ref.where(filter=FieldFilter('status', '==', status))
        rows = [_partner_row(d) for d in ref.limit(limit).stream()]
    q = (query or '').strip().lower()
    if q:
        rows = [r for r in rows if q in ' '.join(
            [r['partner_id'], r['name'], r['phone'], r['city'], r['uid']]).lower()]
    rows.sort(key=lambda r: (r['status'] != 'pending', r['name'].lower()))
    return rows


def _withdrawal_row(doc) -> dict:
    d = doc.to_dict() or {}
    payout = d.get('payout') or {}
    return {
        'id': doc.id,
        'partner_uid': d.get('partnerUid') or '',
        'partner_id': d.get('partnerId') or '',
        'partner_name': d.get('partnerName') or '',
        'amount': _int(d.get('amount')),
        'status': d.get('status') or '',
        'applied_status': d.get('appliedStatus') or '',
        'utr': d.get('utr') or '',
        'reject_reason': d.get('rejectReason') or '',
        'requested': stamp(d.get('requestedAt')),
        'decided': stamp(d.get('decidedAt')),
        'method': payout.get('method') or '',
        'upi': payout.get('upiId') or '',
        'account_name': payout.get('accountName') or '',
        'account_number': payout.get('accountNumber') or '',
        'ifsc': payout.get('ifsc') or '',
        'display': payout.get('display') or '',
    }


def list_withdrawals(status: str = 'requested', partner_uid: str = '', db=None, limit: int = 200) -> list[dict]:
    if _copy(db):
        from django.db.models import F

        from partners.models import PartnerWithdrawal

        filters = {'status': status} if status in WITHDRAWAL_STATUSES else {}
        if partner_uid:
            filters['partner_uid'] = partner_uid
        return _copied_rows(PartnerWithdrawal, _withdrawal_row, limit,
                            [F('requested_at').desc(nulls_last=True), 'id'], **filters)
    db = db or _db()
    ref = db.collection('partnerWithdrawals')
    if status in WITHDRAWAL_STATUSES:
        ref = ref.where(filter=FieldFilter('status', '==', status))
    if partner_uid:
        ref = ref.where(filter=FieldFilter('partnerUid', '==', partner_uid))
    rows = [_withdrawal_row(d) for d in ref.limit(limit).stream()]
    rows.sort(key=lambda r: r['requested'], reverse=True)
    return rows


def _commission_row(doc) -> dict:
    d = doc.to_dict() or {}
    return {
        'order_id': doc.id,
        'partner_uid': d.get('partnerUid') or '',
        'partner_id': d.get('partnerId') or '',
        'status': d.get('status') or '',
        'amount': _int(d.get('amount')),
        'quantity': _int(d.get('quantity')),
        'source': d.get('source') or '',
        'created': stamp(d.get('createdAt')),
        'available_at': stamp(d.get('availableAt')),
        'reversed_reason': d.get('reversedReason') or '',
        'reverse_requested': d.get('adminAction') == 'reverse',
    }


def list_commissions(status: str = '', partner_uid: str = '', db=None, limit: int = 300) -> list[dict]:
    if _copy(db):
        from django.db.models import F

        from partners.models import PartnerCommission

        filters = {'status': status} if status in COMMISSION_STATUSES else {}
        if partner_uid:
            filters['partner_uid'] = partner_uid
        return _copied_rows(PartnerCommission, _commission_row, limit,
                            [F('created_at').desc(nulls_last=True), 'id'], **filters)
    db = db or _db()
    ref = db.collection('partnerCommissions')
    if status in COMMISSION_STATUSES:
        ref = ref.where(filter=FieldFilter('status', '==', status))
    if partner_uid:
        ref = ref.where(filter=FieldFilter('partnerUid', '==', partner_uid))
    rows = [_commission_row(d) for d in ref.limit(limit).stream()]
    rows.sort(key=lambda r: r['created'], reverse=True)
    return rows


def partner_detail(uid: str, db=None) -> dict | None:
    """Live from Firestore: this is the page decisions are made from."""
    db = db or _db()
    ref = db.collection('partners').document(uid)
    snap = ref.get()
    if not snap.exists:
        return None
    payout_snap = ref.collection('private').document('payout').get()
    ledger = []
    for d in ref.collection('ledger').order_by(
            'createdAt', direction=firestore.Query.DESCENDING).limit(100).stream():
        e = d.to_dict() or {}
        ledger.append({
            'type': e.get('type') or '',
            'amount': _int(e.get('amount')),
            'note': e.get('note') or '',
            'ref': e.get('ref') or '',
            'created': stamp(e.get('createdAt')),
        })
    return {
        'partner': _partner_row(snap),
        'payout': payout_snap.to_dict() if payout_snap.exists else None,
        'ledger': ledger,
        'commissions': list_commissions(partner_uid=uid, db=db, limit=100),
        'withdrawals': list_withdrawals(status='', partner_uid=uid, db=db, limit=50),
    }


def summary(db=None) -> dict:
    """Counts for the page header (small, bounded reads)."""
    if _copy(db):
        from partners.models import Partner, PartnerWithdrawal

        live = {'deleted_at__isnull': True}
        return {
            'applications': Partner.objects.filter(status='pending', **live).count(),
            'partners': Partner.objects.filter(status='approved', **live).count(),
            'withdrawals': PartnerWithdrawal.objects.filter(status='requested', **live).count(),
        }
    db = db or _db()

    def count(coll, field, value):
        try:
            q = db.collection(coll).where(filter=FieldFilter(field, '==', value))
            return q.count().get()[0][0].value
        except Exception:
            return len(list(db.collection(coll).where(filter=FieldFilter(field, '==', value)).limit(500).stream()))

    return {
        'applications': count('partners', 'status', 'pending'),
        'partners': count('partners', 'status', 'approved'),
        'withdrawals': count('partnerWithdrawals', 'status', 'requested'),
    }


# ─── Decisions ──────────────────────────────────────────────────────────────

def _run_tx(db, fn):
    """Run fn(transaction) in a Firestore transaction (patched in tests)."""
    transaction = db.transaction()

    @firestore.transactional
    def _inner(tx):
        return fn(tx)

    return _inner(transaction)


def decide_partner(uid: str, action: str, actor: str, reason: str = '', db=None) -> str:
    """approve | reject | suspend | reactivate. Returns the new status."""
    given = db
    db = db or _db()
    ref = db.collection('partners').document(uid)
    snap = ref.get()
    if not snap.exists:
        raise PartnerAdminError('Partner not found.')
    current = (snap.to_dict() or {}).get('status')
    reason = (reason or '').strip()[:300]
    allowed = {
        'approve': ({'pending', 'rejected'}, 'approved'),
        'reject': ({'pending'}, 'rejected'),
        'suspend': ({'approved'}, 'suspended'),
        'reactivate': ({'suspended'}, 'approved'),
    }
    if action not in allowed:
        raise PartnerAdminError('Unknown action.')
    from_states, new_status = allowed[action]
    if current not in from_states:
        raise PartnerAdminError(f'Cannot {action} a partner who is {current or "unknown"}.')
    if action in ('reject', 'suspend') and len(reason) < 4:
        raise PartnerAdminError('Give a short reason (at least 4 characters).')
    update = {
        'status': new_status,
        'reviewedBy': actor,
        'reviewedAt': firestore.SERVER_TIMESTAMP,
        'updatedAt': firestore.SERVER_TIMESTAMP,
    }
    if action == 'reject':
        update['rejectReason'] = reason
    if action == 'suspend':
        update['suspendReason'] = reason
    if action == 'approve':
        update['rejectReason'] = firestore.DELETE_FIELD
    ref.update(update)
    db.collection('partner_admin_audit').add({
        'kind': 'partner', 'action': action, 'uid': uid, 'reason': reason,
        'actor': actor, 'at': firestore.SERVER_TIMESTAMP,
    })
    _refresh(given, 'refresh_partner', uid)
    return new_status


def decide_withdrawal(withdrawal_id: str, action: str, actor: str,
                      utr: str = '', reason: str = '', db=None) -> str:
    """paid (needs a UTR) | rejected (needs a reason). Only from 'requested'."""
    given = db
    db = db or _db()
    ref = db.collection('partnerWithdrawals').document(withdrawal_id)
    utr = (utr or '').strip()
    reason = (reason or '').strip()[:300]
    if action == 'paid' and not UTR_RE.match(utr):
        raise PartnerAdminError('Enter the bank / UPI reference (UTR), 6–40 letters or digits.')
    if action == 'rejected' and len(reason) < 4:
        raise PartnerAdminError('Give a short reason (at least 4 characters).')
    if action not in ('paid', 'rejected'):
        raise PartnerAdminError('Unknown action.')

    def run(tx):
        snap = ref.get(transaction=tx)
        if not snap.exists:
            raise PartnerAdminError('Withdrawal not found.')
        data = snap.to_dict() or {}
        if data.get('status') != 'requested':
            raise PartnerAdminError(f"This withdrawal is already {data.get('status')}.")
        update = {
            'status': action,
            'decidedBy': actor,
            'updatedAt': firestore.SERVER_TIMESTAMP,
        }
        if action == 'paid':
            update['utr'] = utr
            update['paidAt'] = firestore.SERVER_TIMESTAMP
        else:
            update['rejectReason'] = reason
        tx.update(ref, update)
        return data.get('partnerUid') or ''

    partner_uid = _run_tx(db, run)
    db.collection('partner_admin_audit').add({
        'kind': 'withdrawal', 'action': action, 'id': withdrawal_id, 'utr': utr,
        'reason': reason, 'actor': actor, 'at': firestore.SERVER_TIMESTAMP,
    })
    if partner_uid:
        _refresh(given, 'refresh_partner', partner_uid, withdrawal_id=withdrawal_id)
    return action


def request_commission_reversal(order_id: str, reason: str, actor: str, db=None) -> None:
    given = db
    db = db or _db()
    reason = (reason or '').strip()[:300]
    if len(reason) < 4:
        raise PartnerAdminError('Give a short reason (at least 4 characters).')
    ref = db.collection('partnerCommissions').document(order_id)
    snap = ref.get()
    if not snap.exists:
        raise PartnerAdminError('Commission not found.')
    if (snap.to_dict() or {}).get('status') == 'reversed':
        raise PartnerAdminError('Already reversed.')
    ref.update({
        'adminAction': 'reverse',
        'adminReason': reason,
        'adminActor': actor,
        'updatedAt': firestore.SERVER_TIMESTAMP,
    })
    db.collection('partner_admin_audit').add({
        'kind': 'commission', 'action': 'reverse', 'orderId': order_id,
        'reason': reason, 'actor': actor, 'at': firestore.SERVER_TIMESTAMP,
    })
    partner_uid = (snap.to_dict() or {}).get('partnerUid') or ''
    if partner_uid:
        _refresh(given, 'refresh_partner', partner_uid, commission_id=order_id)


# ─── Website referral ───────────────────────────────────────────────────────

REF_COOKIE = 'sudotag_partner_ref'
REF_COOKIE_DAYS = 30


def normalize_code(raw: Any) -> str:
    s = re.sub(r'[^A-Z0-9]', '', str(raw or '').strip().upper())
    return s if 4 <= len(s) <= 16 else ''


def remember_ref(request, response, db=None):
    """If the URL carries ?ref=CODE for an active partner, keep it for 30 days."""
    code = normalize_code(request.GET.get('ref'))
    if not code:
        return response
    try:
        if is_active_code(code, db=db):
            response.set_cookie(
                REF_COOKIE, code,
                max_age=REF_COOKIE_DAYS * 24 * 3600,
                samesite='Lax',
                secure=request.is_secure(),
                httponly=True,
            )
    except Exception:
        pass  # never break the page over a referral
    return response


def current_ref(request) -> str:
    """Code from ?ref= (this visit) or the cookie (earlier visit)."""
    return normalize_code(request.GET.get('ref')) or normalize_code(request.COOKIES.get(REF_COOKIE))


def is_active_code(code: str, db=None) -> bool:
    code = normalize_code(code)
    if not code:
        return False
    if _copy(db):
        from partners.models import PartnerCode

        if PartnerCode.objects.filter(code=code, active=True, deleted_at__isnull=True).exists():
            return True
        # Not active in the copy: ask Firestore, so a code issued minutes ago still works.
    db = db or _db()
    snap = db.collection('partnerCodes').document(code).get()
    return bool(snap.exists and (snap.to_dict() or {}).get('active') is True)
