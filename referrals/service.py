"""Refer & Earn — port of the referral Cloud Functions in functions/index.js
(ensureReferralCode, applyReferralCode, markReferralSuccessful), plus the
Firestore -> PostgreSQL import and the reads the app and admin panel use.

Error codes and messages match the callables, so the app shows the same text.
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone

from django.utils import timezone as dj_tz

from api import firebase
from api.errors import ApiError
from api.mirror import decode, encode

from .models import Referral, ReferralCode, ReferralImport, ReferralProfile

logger = logging.getLogger(__name__)

CODES = 'referralCodes'
REFERRALS = 'referrals'
USERS = 'users'

CODE_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
PENDING, SUCCESSFUL, REWARDED = 'pending', 'successful', 'rewarded'
LINK = 'https://sudotag.com/r/{code}'


def normalize_code(raw) -> str:
    return ''.join(ch for ch in str(raw or '').strip().upper() if ch.isascii() and ch.isalnum())


def empty_stats() -> dict:
    return {'totalReferrals': 0, 'successfulReferrals': 0, 'pendingReferrals': 0, 'rewardsEarned': 0}


def link_for(code: str) -> str:
    return LINK.format(code=code)


def _num(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0


def _int(value) -> int:
    return int(_num(value))


def _dt(value):
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return None


def _server_time():
    from firebase_admin import firestore

    return firestore.SERVER_TIMESTAMP


def _merged_stats(raw) -> dict:
    return {**empty_stats(), **(raw if isinstance(raw, dict) else {})}


# ─── Firestore -> PostgreSQL ─────────────────────────────────────────────────
def _store_code(code: str, data: dict) -> ReferralCode:
    row, _ = ReferralCode.objects.update_or_create(code=code, defaults={
        'user_id': str(data.get('userId') or '')[:128],
        'user_name': str(data.get('userName') or '')[:200],
        'contact_number': str(data.get('contactNumber') or '')[:40],
        'is_active': data.get('isActive') is not False,
        'created_at': _dt(data.get('createdAt')),
        'document': encode(data), 'synced_at': dj_tz.now(), 'deleted_at': None,
    })
    return row


def _store_referral(referral_id: str, data: dict) -> Referral:
    row, _ = Referral.objects.update_or_create(id=referral_id, defaults={
        'referrer_user_id': str(data.get('referrerUserId') or '')[:128],
        'referred_user_id': str(data.get('referredUserId') or referral_id)[:128],
        'referral_code': str(data.get('referralCode') or '')[:32],
        'status': str(data.get('status') or PENDING)[:16],
        'reward_status': str(data.get('rewardStatus') or '')[:16],
        'reward_amount': _num(data.get('rewardAmount')),
        'registered_at': _dt(data.get('registeredAt')),
        'document': encode(data), 'synced_at': dj_tz.now(), 'deleted_at': None,
    })
    return row


def _store_profile(uid: str, data: dict) -> ReferralProfile:
    raw_stats = data.get('referralStats')
    stats = raw_stats if isinstance(raw_stats, dict) else None
    row, _ = ReferralProfile.objects.update_or_create(user_id=uid, defaults={
        'referral_code': str(data.get('referralCode') or '')[:32],
        'referred_by_code': str(data.get('referredByCode') or '')[:32],
        'referred_by_user_id': str(data.get('referredByUserId') or '')[:128],
        'stats': encode(stats) if stats is not None else None,
        'total_referrals': _int((stats or {}).get('totalReferrals')),
        'successful_referrals': _int((stats or {}).get('successfulReferrals')),
        'full_name': str(data.get('fullName') or '')[:200],
        'contact_number': str(data.get('contactNumber') or '')[:40],
        'email_address': str(data.get('emailAddress') or '')[:254],
        'synced_at': dj_tz.now(), 'deleted_at': None,
    })
    return row


def import_code(db, code: str) -> None:
    snap = db.collection(CODES).document(code).get()
    if snap.exists:
        _store_code(code, snap.to_dict() or {})
    else:
        ReferralCode.objects.filter(code=code, deleted_at__isnull=True).update(deleted_at=dj_tz.now())


def import_referral(db, referral_id: str) -> None:
    snap = db.collection(REFERRALS).document(referral_id).get()
    if snap.exists:
        _store_referral(referral_id, snap.to_dict() or {})
    else:
        Referral.objects.filter(id=referral_id, deleted_at__isnull=True).update(deleted_at=dj_tz.now())


def import_profile(db, uid: str) -> None:
    snap = db.collection(USERS).document(uid).get()
    if snap.exists:
        _store_profile(uid, snap.to_dict() or {})
    else:
        ReferralProfile.objects.filter(user_id=uid, deleted_at__isnull=True).update(deleted_at=dj_tz.now())


def _import_collection(db, collection, store, model, key) -> dict:
    """Upsert every document; rows whose document is gone are kept, marked deleted."""
    seen = set()
    for snap in db.collection(collection).stream():
        seen.add(snap.id)
        store(snap.id, snap.to_dict() or {})
    gone = model.objects.filter(deleted_at__isnull=True).exclude(**{f'{key}__in': seen})
    return {'imported': len(seen), 'marked_deleted': gone.update(deleted_at=dj_tz.now())}


def import_everything(db) -> dict:
    stats = {
        'codes': _import_collection(db, CODES, _store_code, ReferralCode, 'code'),
        'referrals': _import_collection(db, REFERRALS, _store_referral, Referral, 'id'),
        'profiles': _import_collection(db, USERS, _store_profile, ReferralProfile, 'user_id'),
    }
    ReferralImport.objects.update_or_create(id='full', defaults={'finished_at': dj_tz.now()})
    return stats


def postgres_ready() -> bool:
    try:
        return ReferralImport.objects.filter(id='full').exists()
    except Exception:  # tables missing before migrate
        return False


def _sync_after_write(db, *, uids=(), codes=(), referral_ids=()) -> None:
    """Copy what a write just changed; the worker retries anything that fails here."""
    try:
        for uid in uids:
            import_profile(db, uid)
        for code in codes:
            import_code(db, code)
        for referral_id in referral_ids:
            import_referral(db, referral_id)
    except Exception:
        logger.exception('referrals: copy to PostgreSQL failed (worker will retry)')


# ─── ensureReferralCode ──────────────────────────────────────────────────────
def _candidate_code() -> str:
    return 'SUDO' + ''.join(secrets.choice(CODE_ALPHABET) for _ in range(8))


def allocate_code(db, max_attempts: int = 12) -> str:
    for _ in range(max_attempts):
        code = _candidate_code()
        if not db.collection(CODES).document(code).get().exists:
            return code
    raise ApiError('resource-exhausted', 'Could not allocate a unique referral code.')


def _code_doc(uid: str, user: dict) -> dict:
    return {'userId': uid, 'userName': user.get('fullName') or '',
            'contactNumber': user.get('contactNumber') or '',
            'createdAt': _server_time(), 'isActive': True}


def ensure_code(db, uid: str) -> dict:
    """Idempotent: returns the caller's code, creating it (and the index doc) if needed."""
    user_ref = db.collection(USERS).document(uid)
    snap = user_ref.get()
    if not snap.exists:
        raise ApiError('failed-precondition', 'Create your profile before requesting a referral code.')
    user = snap.to_dict() or {}
    existing = normalize_code(user.get('referralCode'))
    if existing:
        code_ref = db.collection(CODES).document(existing)
        if not code_ref.get().exists:
            code_ref.set(_code_doc(uid, user))
        _sync_after_write(db, uids=[uid], codes=[existing])
        return {'success': True, 'referralCode': existing, 'referralLink': link_for(existing),
                'stats': user.get('referralStats') or empty_stats()}

    code = allocate_code(db)

    def run(tx):
        fresh = (user_ref.get(transaction=tx).to_dict() or {})
        if normalize_code(fresh.get('referralCode')):
            return
        code_ref = db.collection(CODES).document(code)
        if code_ref.get(transaction=tx).exists:
            raise ApiError('aborted', 'Referral code collision — please retry.')
        tx.set(code_ref, _code_doc(uid, fresh))
        tx.update(user_ref, {'referralCode': code, 'referralStats': fresh.get('referralStats') or empty_stats()})

    firebase.run_transaction(db, run)
    updated = user_ref.get().to_dict() or {}
    final = normalize_code(updated.get('referralCode')) or code
    _sync_after_write(db, uids=[uid], codes=[final])
    return {'success': True, 'referralCode': final, 'referralLink': link_for(final),
            'stats': updated.get('referralStats') or empty_stats()}


# ─── applyReferralCode ───────────────────────────────────────────────────────
def apply_code(db, uid: str, raw_code) -> dict:
    code = normalize_code(raw_code)
    if len(code) < 4:
        raise ApiError('invalid-argument', 'A valid referral code is required.')
    referred_ref = db.collection(USERS).document(uid)
    code_ref = db.collection(CODES).document(code)
    referral_ref = db.collection(REFERRALS).document(uid)  # one referral per referred user

    def run(tx):
        referred_snap = referred_ref.get(transaction=tx)
        code_snap = code_ref.get(transaction=tx)
        if not referred_snap.exists:
            raise ApiError('failed-precondition', 'Create your profile before applying a referral code.')
        code_data = code_snap.to_dict() or {}
        if not code_snap.exists or code_data.get('isActive') is False:
            raise ApiError('not-found', 'This referral code is invalid or inactive.')
        referred = referred_snap.to_dict() or {}
        referrer_uid = str(code_data.get('userId') or '')
        if not referrer_uid:
            raise ApiError('failed-precondition', 'Referral code is misconfigured.')
        if referrer_uid == uid:
            raise ApiError('failed-precondition', 'You cannot use your own referral code.')
        if referred.get('referredByUserId') or referred.get('referredByCode'):
            raise ApiError('already-exists', 'A referral has already been applied to this account.')
        if referral_ref.get(transaction=tx).exists:
            raise ApiError('already-exists', 'A referral has already been recorded for this account.')
        referrer_ref = db.collection(USERS).document(referrer_uid)
        referrer_snap = referrer_ref.get(transaction=tx)
        if not referrer_snap.exists:
            raise ApiError('not-found', 'Referrer account was not found.')
        referrer = referrer_snap.to_dict() or {}
        stats = _merged_stats(referrer.get('referralStats'))
        stats['totalReferrals'] = _num(stats['totalReferrals']) + 1
        stats['pendingReferrals'] = _num(stats['pendingReferrals']) + 1
        now = _server_time()
        tx.set(referral_ref, {
            'referrerUserId': referrer_uid,
            'referrerName': referrer.get('fullName') or code_data.get('userName') or '',
            'referrerContact': referrer.get('contactNumber') or code_data.get('contactNumber') or '',
            'referralCode': code,
            'referredUserId': uid,
            'referredUserName': referred.get('fullName') or '',
            'referredContact': referred.get('contactNumber') or '',
            'registeredAt': now,
            'status': PENDING,
            'rewardStatus': 'none',
            'rewardAmount': 0,
            'createdAt': now,
            'updatedAt': now,
        })
        tx.update(referred_ref, {'referredByCode': code, 'referredByUserId': referrer_uid})
        tx.update(referrer_ref, {'referralStats': _js_numbers(stats)})
        return referrer_uid

    referrer_uid = firebase.run_transaction(db, run)
    logger.info('applyReferralCode: referred=%s code=%s referrer=%s', uid, code, referrer_uid)
    _sync_after_write(db, uids=[uid, referrer_uid], referral_ids=[uid])
    return {'success': True, 'referralId': uid, 'referrerUserId': referrer_uid,
            'referralCode': code, 'status': PENDING}


def _js_numbers(stats: dict) -> dict:
    """Whole numbers as int, like JS numbers written by the Cloud Function."""
    return {k: (int(v) if isinstance(v, float) and v.is_integer() else v) for k, v in stats.items()}


# ─── markReferralSuccessful ──────────────────────────────────────────────────
def mark_successful(db, uid: str) -> dict:
    docs = list(db.collection(REFERRALS).where('referredUserId', '==', uid).limit(1).stream())
    if not docs:
        return {'success': True, 'updated': False, 'reason': 'no_referral'}
    doc = docs[0]
    if (doc.to_dict() or {}).get('status') in (SUCCESSFUL, REWARDED):
        return {'success': True, 'updated': False, 'reason': 'already_successful'}
    ref = doc.reference

    def run(tx):
        referral = ref.get(transaction=tx).to_dict() or {}
        if referral.get('status') != PENDING:
            return None
        referrer_uid = str(referral.get('referrerUserId') or '')
        referrer_ref = db.collection(USERS).document(referrer_uid) if referrer_uid else None
        referrer_snap = referrer_ref.get(transaction=tx) if referrer_ref else None
        tx.update(ref, {'status': SUCCESSFUL, 'updatedAt': _server_time()})
        if referrer_snap is not None and referrer_snap.exists:
            stats = _merged_stats((referrer_snap.to_dict() or {}).get('referralStats'))
            stats['pendingReferrals'] = max(0, _num(stats['pendingReferrals']) - 1)
            stats['successfulReferrals'] = _num(stats['successfulReferrals']) + 1
            tx.update(referrer_ref, {'referralStats': _js_numbers(stats)})
        return referrer_uid

    referrer_uid = firebase.run_transaction(db, run)
    _sync_after_write(db, uids=[u for u in [referrer_uid] if u], referral_ids=[doc.id])
    return {'success': True, 'updated': True, 'referralId': doc.id}


# ─── reads (PostgreSQL) ──────────────────────────────────────────────────────
def referral_json(row: Referral) -> dict:
    data = decode(row.document)
    out = {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in data.items()}
    out['id'] = row.id
    return out


def referrals_for(referrer_uid: str) -> list[Referral]:
    rows = Referral.objects.filter(referrer_user_id=referrer_uid, deleted_at__isnull=True)
    return sorted(rows, key=lambda r: r.registered_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)


def stats_for(uid: str) -> dict:
    profile = ReferralProfile.objects.filter(user_id=uid, deleted_at__isnull=True).first()
    if profile is None or profile.stats is None:
        return empty_stats()
    return _merged_stats(decode(profile.stats))
