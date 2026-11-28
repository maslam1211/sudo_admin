"""Scanner → vehicle owner contact, decided on the server.

    POST /api/v1/vehicles/{vehicle_id}/sms   {message}            signed in
    POST /api/v1/calls/register              {from, destination, qr_id, …}  signed in

The SMS endpoint replaces lib/service/sms_service.dart, which sent the MSG91
campaign SMS from the phone with the auth key compiled in, to a number the
scanner's app supplied. Here the server resolves the owner's number and
applies the same checks as the web scan page (`_push_failed_sms_fallback`).
"""

from __future__ import annotations

import json
import logging

from ninja import Router, Schema

from admin_app.family_assignment import effective_contact_number
from admin_app.msg91_vehicle_sms import send_vehicle_issue_sms
from admin_app.owner_live_status import parse_owner_live_status
from admin_app.scanner_contact_prefs import (
    merge_user_scanner_subdocuments,
    merge_vehicle_scanner_subdocuments,
    scanner_effective_channels_now,
    scanner_pref_merged_dict,
    scanner_user_app_prefs_from_merged,
)

from .. import firebase, ratelimit
from ..errors import ApiError
from ..security import firebase_auth

logger = logging.getLogger(__name__)

router = Router(tags=['vehicle-contact'], auth=firebase_auth)

SMS_MAX_CHARS = 200          # MSG91 campaign variable limit (msg91_vehicle_sms.py)
SMS_PER_SCANNER_10MIN = 5
SMS_PER_SCANNER_DAY = 20
SMS_PER_VEHICLE_HOUR = 10
CALL_REGISTER_PER_UID_10MIN = 10


class SmsIn(Schema):
    message: str


class SmsOut(Schema):
    sent: bool


def is_blocked(db, *, blocker_id: str, blocked_id: str) -> bool:
    docs = (
        db.collection('blocked_users')
        .where('blockerId', '==', blocker_id)
        .where('blockedUserId', '==', blocked_id)
        .limit(1)
        .stream()
    )
    return any(True for _ in docs)


def owner_sms_destination(db, vehicle_id: str):
    """(digits, owner_id) when the owner currently accepts scanner SMS.

    Raises ApiError with a user-facing reason otherwise.
    """
    vehicle_ref = db.collection('vehicles').document(vehicle_id)
    vehicle_snap = vehicle_ref.get()
    if not vehicle_snap.exists:
        raise ApiError('not-found', 'Vehicle not found.')
    vehicle_data = vehicle_snap.to_dict() or {}
    owner_id = str(vehicle_data.get('ownerId') or '').strip()
    if not owner_id:
        raise ApiError('failed-precondition', "This vehicle isn't linked to an owner.")

    user_ref = db.collection('users').document(owner_id)
    user_snap = user_ref.get()
    user_data = user_snap.to_dict() if user_snap.exists else {}
    user_data = merge_user_scanner_subdocuments(db, user_ref, user_data or {})
    vehicle_data = merge_vehicle_scanner_subdocuments(db, vehicle_ref, vehicle_data)

    effective = scanner_effective_channels_now(user_data, vehicle_data)
    prefs = scanner_user_app_prefs_from_merged(scanner_pref_merged_dict(user_data, vehicle_data))
    if not (effective['sms'] and prefs['owner_sms_allowed']):
        raise ApiError('failed-precondition', 'The owner has turned off SMS.')
    if not parse_owner_live_status(user_data)['allows_messaging']:
        raise ApiError('failed-precondition', "The owner isn't taking messages right now.")

    digits = effective_contact_number(vehicle_data, user_data)
    if not digits or len(digits) != 10:
        raise ApiError('failed-precondition', "The owner hasn't added a mobile number.")
    return digits, owner_id


@router.post('/vehicles/{vehicle_id}/sms', response=SmsOut)
def send_owner_sms(request, vehicle_id: str, body: SmsIn):
    message = ' '.join(str(body.message or '').split())
    if not message:
        raise ApiError('invalid-argument', 'Please select or enter a message to send.')
    if len(message) > SMS_MAX_CHARS:
        raise ApiError('invalid-argument', f'Keep the message under {SMS_MAX_CHARS} characters.')

    uid = request.auth.uid
    db = firebase.firestore_db()
    digits, owner_id = owner_sms_destination(db, vehicle_id)
    if owner_id != uid and is_blocked(db, blocker_id=owner_id, blocked_id=uid):
        raise ApiError('permission-denied', "You can't message this owner.")

    ratelimit.hit(f'sms:scanner10:{uid}', limit=SMS_PER_SCANNER_10MIN, window_seconds=600,
                  message='You have sent several SMS just now. Please wait a few minutes.')
    ratelimit.hit(f'sms:scannerday:{uid}', limit=SMS_PER_SCANNER_DAY, window_seconds=86400,
                  message="You've reached today's SMS limit.")
    ratelimit.hit(f'sms:vehicle:{vehicle_id}', limit=SMS_PER_VEHICLE_HOUR, window_seconds=3600,
                  message='This owner has received several SMS already. Please try again later.')

    result = send_vehicle_issue_sms(digits_10=digits, message=message)
    if not result.get('ok'):
        logger.warning('Scanner SMS failed vehicle=%s err=%s', vehicle_id, result.get('error'))
        raise ApiError('unavailable', 'Failed to send SMS. Please try again later.')
    logger.info('Scanner SMS sent vehicle=%s scanner=%s owner=%s', vehicle_id, uid, owner_id)
    return {'sent': True}


def _caller_contact_10(db, uid: str, token_phone: str) -> set[str]:
    numbers = set()
    token_digits = ''.join(c for c in token_phone if c.isdigit())
    if len(token_digits) >= 10:
        numbers.add(token_digits[-10:])
    snap = db.collection('users').document(uid).get()
    if snap.exists:
        stored = ''.join(c for c in str((snap.to_dict() or {}).get('contactNumber') or '') if c.isdigit())
        if len(stored) >= 10:
            numbers.add(stored[-10:])
    return numbers


@router.post('/calls/register')
def register_call(request):
    """Signed-in version of /admin/api/call/register for the mobile app.

    The PBX routes a call by the caller's number, so registering an intent for
    someone else's number would redirect *their* next call. The legacy endpoint
    can't check that (web scanners have no account); this one requires `from`
    to be the signed-in user's own number, then runs the existing view.
    """
    try:
        body = json.loads(request.body or b'{}')
    except (ValueError, TypeError):
        raise ApiError('invalid-argument', 'Invalid request.')
    if not isinstance(body, dict):
        raise ApiError('invalid-argument', 'Invalid request.')

    from_digits = ''.join(c for c in str(body.get('from') or '') if c.isdigit())[-10:]
    if len(from_digits) != 10:
        raise ApiError('invalid-argument', 'Add your mobile number in Profile before calling.')
    uid = request.auth.uid
    db = firebase.firestore_db()
    if from_digits not in _caller_contact_10(db, uid, request.auth.phone_number):
        raise ApiError('permission-denied', 'Calls can only be placed from your own mobile number.')

    ratelimit.hit(f'call-register:{uid}', limit=CALL_REGISTER_PER_UID_10MIN, window_seconds=600,
                  message='Too many call attempts. Please wait a few minutes.')

    from call_routing.views import register_call_destination

    return register_call_destination(request)
