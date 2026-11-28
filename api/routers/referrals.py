"""Refer & Earn.

    POST /api/v1/referrals/code             signed in  (was ensureReferralCode)
    POST /api/v1/referrals/apply            signed in  {referralCode}  (was applyReferralCode)
    POST /api/v1/referrals/mark-successful  signed in  (was markReferralSuccessful)
    GET  /api/v1/referrals                  signed in  {referrals: mine as referrer, newest first, stats}
    GET  /api/v1/referral-codes/{code}      public     who a code belongs to (invite page)

Response bodies match the callables' return values.
"""

from __future__ import annotations

from ninja import Router, Schema

from referrals import service

from .. import firebase, ratelimit
from ..errors import ApiError
from ..security import firebase_auth

public_router = Router(tags=['referrals'])
router = Router(tags=['referrals'], auth=firebase_auth)

APPLY_PER_UID_HOUR = 10
LOOKUPS_PER_IP_HOUR = 60


class ApplyIn(Schema):
    referralCode: str = ''


@router.post('/referrals/code')
def ensure_code(request):
    return service.ensure_code(firebase.firestore_db(), request.auth.uid)


@router.post('/referrals/apply')
def apply_code(request, body: ApplyIn):
    ratelimit.hit(f'referral-apply:{request.auth.uid}', limit=APPLY_PER_UID_HOUR, window_seconds=3600)
    return service.apply_code(firebase.firestore_db(), request.auth.uid, body.referralCode)


@router.post('/referrals/mark-successful')
def mark_successful(request):
    return service.mark_successful(firebase.firestore_db(), request.auth.uid)


@router.get('/referrals')
def my_referrals(request):
    uid = request.auth.uid
    return {'referrals': [service.referral_json(r) for r in service.referrals_for(uid)],
            'stats': service.stats_for(uid)}


@public_router.get('/referral-codes/{code}')
def lookup_code(request, code: str):
    """Only the first name is shown — the invite page needs no contact details."""
    ip = request.META.get('REMOTE_ADDR', '')
    ratelimit.hit(f'referral-lookup:{ip}', limit=LOOKUPS_PER_IP_HOUR, window_seconds=3600)
    from referrals.models import ReferralCode

    row = ReferralCode.objects.filter(code=service.normalize_code(code), deleted_at__isnull=True).first()
    if row is None or not row.is_active:
        raise ApiError('not-found', 'This referral code is invalid or inactive.')
    return {'code': row.code, 'firstName': (row.user_name or '').split(' ')[0],
            'referralLink': service.link_for(row.code)}
