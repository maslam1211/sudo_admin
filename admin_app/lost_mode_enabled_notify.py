"""
Lost Mode ON → automatic owner SMS via the existing MSG91 vehicle-issue campaign.

Reuses ``send_vehicle_issue_sms`` (same campaign URL / authkey / DLT variable
path as scanner "Send SMS"). Does not add any new MSG91 route or sender config.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping, Optional

from google.cloud import firestore

from .family_assignment import vehicle_owner_contact_number
from .fcm_push import store_inbox_notification
from .msg91_vehicle_sms import send_vehicle_issue_sms
from .scanner_contact_prefs import normalize_phone_digits

logger = logging.getLogger(__name__)

LOST_MODE_ENABLED_SMS_TITLE = 'Lost Mode enabled'
LOST_MODE_ENABLED_INBOX_TYPE = 'lost_mode_enabled'
HISTORY_COLLECTION = 'lostModeNotificationHistory'


def build_lost_mode_enabled_sms_body(
    *,
    registration_number: str = '',
    vehicle_name: str = '',
) -> str:
    """Short DLT campaign variable text (existing vehicle-issue template)."""
    plate = (registration_number or '').strip().upper()
    name = (vehicle_name or '').strip()
    label = plate or name or 'your vehicle'
    return (
        f'Lost Mode is now ON for {label}. '
        'Anyone who scans your SUDO Tag can tip you to help recovery.'
    )[:200]


def _owner_digits(
    vehicle_data: Optional[Mapping[str, Any]],
    user_data: Optional[Mapping[str, Any]],
) -> Optional[str]:
    return (
        vehicle_owner_contact_number(vehicle_data, user_data)
        or normalize_phone_digits((vehicle_data or {}).get('ownerContact'))
        or normalize_phone_digits((user_data or {}).get('contactNumber'))
    )


def _write_history(
    db: firestore.Client,
    *,
    vehicle_id: str,
    owner_id: str,
    status: str,
    phone_last4: str = '',
    sms_body: str = '',
    msg91: Optional[Mapping[str, Any]] = None,
    error: Optional[str] = None,
    inbox_notification_id: Optional[str] = None,
) -> str:
    ref = db.collection(HISTORY_COLLECTION).document()
    doc: dict[str, Any] = {
        'vehicleId': str(vehicle_id or ''),
        'ownerId': str(owner_id or ''),
        'event': 'lost_mode_enabled',
        'channel': 'sms',
        'status': status,
        'phoneLast4': phone_last4,
        'smsBody': (sms_body or '')[:200],
        'msg91': dict(msg91 or {}),
        'error': error,
        'inboxNotificationId': inbox_notification_id or '',
        'createdAt': firestore.SERVER_TIMESTAMP,
    }
    ref.set(doc)
    return ref.id


def notify_owner_lost_mode_enabled(
    db: firestore.Client,
    *,
    vehicle_id: str,
    vehicle_data: Optional[Mapping[str, Any]] = None,
    user_data: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """
    Send the existing MSG91 vehicle-issue SMS when Lost Mode turns ON.

    Loads vehicle/owner from Firestore when docs are not passed in.
    Always writes ``lostModeNotificationHistory``; also stores an inbox row
    when SMS is queued successfully.
    """
    result: dict[str, Any] = {
        'ok': False,
        'sms_sent': False,
        'skipped_reason': None,
        'history_id': None,
        'inbox_notification_id': None,
        'error': None,
    }

    vid = (vehicle_id or '').strip()
    if not vid:
        result['skipped_reason'] = 'missing_vehicle_id'
        result['error'] = 'missing_vehicle_id'
        return result

    if vehicle_data is None:
        vdoc = db.collection('vehicles').document(vid).get()
        if not vdoc.exists:
            result['skipped_reason'] = 'vehicle_not_found'
            result['error'] = 'vehicle_not_found'
            return result
        vehicle_data = vdoc.to_dict() or {}

    owner_id = str((vehicle_data or {}).get('ownerId') or '').strip()
    if not owner_id:
        result['skipped_reason'] = 'no_owner'
        result['error'] = 'no_owner'
        _write_history(
            db,
            vehicle_id=vid,
            owner_id='',
            status='failed',
            error='no_owner',
        )
        return result

    if user_data is None:
        udoc = db.collection('users').document(owner_id).get()
        user_data = udoc.to_dict() if udoc.exists else {}

    digits = _owner_digits(vehicle_data, user_data)
    if not digits or len(digits) != 10:
        result['skipped_reason'] = 'no_phone'
        result['error'] = 'no_phone'
        history_id = _write_history(
            db,
            vehicle_id=vid,
            owner_id=owner_id,
            status='failed',
            error='no_phone',
        )
        result['history_id'] = history_id
        logger.warning(
            'Lost Mode enabled SMS skipped vehicle=%s reason=no_phone',
            vid,
        )
        return result

    sms_body = build_lost_mode_enabled_sms_body(
        registration_number=str(
            (vehicle_data or {}).get('registrationNumber') or ''
        ),
        vehicle_name=str(
            (vehicle_data or {}).get('vehicleName')
            or (vehicle_data or {}).get('vehicleNameWithMake')
            or ''
        ),
    )

    sms_result = send_vehicle_issue_sms(digits_10=digits, message=sms_body)
    phone_last4 = digits[-4:]

    if not sms_result.get('ok'):
        err = str(sms_result.get('error') or 'sms_failed')
        history_id = _write_history(
            db,
            vehicle_id=vid,
            owner_id=owner_id,
            status='failed',
            phone_last4=phone_last4,
            sms_body=sms_body,
            msg91=sms_result.get('api') or {},
            error=err,
        )
        result['history_id'] = history_id
        result['skipped_reason'] = 'sms_failed'
        result['error'] = err
        logger.warning(
            'Lost Mode enabled SMS failed vehicle=%s err=%s',
            vid,
            err,
        )
        return result

    inbox_id = None
    try:
        stored = store_inbox_notification(
            db,
            user_id=owner_id,
            title=LOST_MODE_ENABLED_SMS_TITLE,
            body=sms_body,
            type_value=LOST_MODE_ENABLED_INBOX_TYPE,
            data={
                'vehicleId': vid,
                'lostMode': 'true',
                'channel': 'sms',
                'notificationType': LOST_MODE_ENABLED_INBOX_TYPE,
                'type': LOST_MODE_ENABLED_INBOX_TYPE,
            },
        )
        inbox_id = stored.get('notification_id')
    except Exception as exc:
        logger.warning(
            'Lost Mode enabled inbox write failed vehicle=%s: %s',
            vid,
            exc,
        )

    history_id = _write_history(
        db,
        vehicle_id=vid,
        owner_id=owner_id,
        status='sent',
        phone_last4=phone_last4,
        sms_body=sms_body,
        msg91=sms_result.get('api') or {},
        inbox_notification_id=inbox_id,
    )

    result.update(
        {
            'ok': True,
            'sms_sent': True,
            'history_id': history_id,
            'inbox_notification_id': inbox_id,
            'phone_last4': phone_last4,
        }
    )
    logger.info(
        'Lost Mode enabled SMS sent vehicle=%s owner=%s ***%s history=%s',
        vid,
        owner_id,
        phone_last4,
        history_id,
    )
    return result
