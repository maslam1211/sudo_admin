"""
Firebase Cloud Messaging helper for the SudoTag **web panel** (Django / Admin SDK).

Use this instead of bare FCM HTTP payloads with only `notification: {title, body}`.
That path misses:
  - Custom sound (`sudotag_notify` / `sudotag_notify.wav` in the mobile apps)
  - Accurate home-screen badge (unseen count from Firestore `notifications`)
  - Call notification typing for the mobile inbox (`incoming_call`)

Must match:
  - functions/index.js (PUSH_SOUND_*, storeInboxNotification, countUnseenNotifications)
  - lib/data/constants/push_notification_sound.dart
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from firebase_admin import firestore, messaging

logger = logging.getLogger(__name__)

PUSH_CHANNEL_ID = 'sudo_notifications'
PUSH_SOUND_ANDROID = 'sudotag_notify'
PUSH_SOUND_IOS = 'sudotag_notify.wav'

# Legacy aliases for imports elsewhere
FCM_ANDROID_CHANNEL_ID = PUSH_CHANNEL_ID
FCM_ANDROID_SOUND = PUSH_SOUND_ANDROID
FCM_IOS_SOUND = PUSH_SOUND_IOS


def _is_truthy(value: Any) -> bool:
    if value is True:
        return True
    if value is False or value is None:
        return False
    return str(value).strip().lower() in ('true', '1', 'yes')


def normalize_notification_type(type_value: Optional[str]) -> str:
    t = (type_value or 'system').strip().lower()
    if t in (
        'incoming_call',
        'voice_call_attempt',
        'voice_call_outgoing',
        'voice_call',
        'call',
        'scanner_call_attempt',
    ) or ('call' in t and 'voice' in t):
        return 'voice_call_outgoing' if 'outgoing' in t else 'incoming_call'
    return t or 'system'


def count_unseen_notifications(db: firestore.Client, user_id: str) -> int:
    """Unseen inbox rows for badge; prefer aggregate count (fast) over full collection scan."""
    uid = (user_id or '').strip()
    if not uid:
        return 0
    try:
        from google.cloud.firestore_v1.aggregation import AggregationQuery
        from google.cloud.firestore_v1.base_query import FieldFilter

        q = (
            db.collection('notifications')
            .where(filter=FieldFilter('userId', '==', uid))
            .where(filter=FieldFilter('seen', '==', False))
        )
        agg_result = AggregationQuery(q).count().get()
        if agg_result and agg_result[0]:
            return int(agg_result[0][0].value)
    except Exception as exc:
        logger.warning('count_unseen_notifications aggregate failed: %s', exc)

    try:
        from google.cloud.firestore_v1.base_query import FieldFilter

        q = (
            db.collection('notifications')
            .where(filter=FieldFilter('userId', '==', uid))
            .where(filter=FieldFilter('seen', '==', False))
        )
        return sum(1 for _ in q.stream())
    except Exception as exc:
        logger.warning('count_unseen_notifications stream failed: %s', exc)
        return 0


def store_inbox_notification(
    db: firestore.Client,
    *,
    user_id: str,
    title: str,
    body: str,
    type_value: str,
    data: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    delivery_id = (
        (data or {}).get('delivery_id')
        or f'{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}'
    )
    payload_data = {**(data or {}), 'delivery_id': str(delivery_id)}
    ref = db.collection('notifications').document()
    ref.set(
        {
            'userId': user_id.strip(),
            'title': (title or 'Notification').strip(),
            'body': (body or '').strip(),
            'type': normalize_notification_type(type_value),
            'data': payload_data,
            'seen': False,
            'createdAt': firestore.SERVER_TIMESTAMP,
        }
    )
    return {'notification_id': ref.id, 'delivery_id': str(delivery_id)}


def build_fcm_message(
    *,
    token: str,
    title: str,
    body: str,
    data: Optional[Dict[str, Any]] = None,
    badge_count: int = 1,
) -> messaging.Message:
    string_data: Dict[str, str] = {}
    if data:
        for key, value in data.items():
            if value is None:
                continue
            if isinstance(value, (dict, list)):
                string_data[str(key)] = str(value)
            else:
                string_data[str(key)] = str(value)

    badge = max(0, int(badge_count or 1))
    if badge < 1:
        badge = 1

    string_data.setdefault('sound', PUSH_SOUND_ANDROID)
    string_data.setdefault('channel_id', PUSH_CHANNEL_ID)

    return messaging.Message(
        token=token.strip(),
        notification=messaging.Notification(title=title, body=body),
        data=string_data,
        android=messaging.AndroidConfig(
            priority='high',
            notification=messaging.AndroidNotification(
                channel_id=PUSH_CHANNEL_ID,
                sound=PUSH_SOUND_ANDROID,
                default_vibrate_timings=True,
                visibility='public',
                priority='high',
                notification_count=badge,
            ),
        ),
        apns=messaging.APNSConfig(
            headers={
                'apns-priority': '10',
                'apns-push-type': 'alert',
            },
            payload=messaging.APNSPayload(
                aps=messaging.Aps(
                    alert=messaging.ApsAlert(title=title, body=body),
                    sound=PUSH_SOUND_IOS,
                    badge=badge,
                    custom_data={'interruption-level': 'active'},
                )
            ),
        ),
    )


def send_push_to_user(
    db: firestore.Client,
    *,
    user_id: str,
    title: str,
    body: str,
    data: Optional[Dict[str, Any]] = None,
    store_inbox: bool = True,
) -> Dict[str, Any]:
    """
    Send push to users/{userId}.fcmToken with custom sound + badge.

    For **call** alerts from the web panel, pass for example:
      type='incoming_call'  (or 'voice_call_attempt')
      data={ 'call_id': '...', 'channel_id': '...', 'caller_id': '...', ... }
    """
    uid = (user_id or '').strip()
    if not uid:
        return {'success': False, 'error': 'NO_USER_ID'}

    user_doc = db.collection('users').document(uid).get()
    if not user_doc.exists:
        return {'success': False, 'error': 'USER_NOT_FOUND'}

    fcm_token = (user_doc.get('fcmToken') or '').strip()
    if not fcm_token:
        return {'success': False, 'error': 'NO_TOKEN'}

    return send_push_to_tokens(
        db,
        user_id=uid,
        tokens=[fcm_token],
        title=title,
        body=body,
        data=data,
        store_inbox=store_inbox,
    )


def send_push_to_tokens(
    db: firestore.Client,
    *,
    user_id: str,
    tokens: List[str],
    title: str,
    body: str,
    data: Optional[Dict[str, Any]] = None,
    store_inbox: bool = True,
) -> Dict[str, Any]:
    """
    Send to one or more FCM tokens (e.g. vehicle + user doc) for the same owner.

    FCM is sent immediately after a single inbox write — not after a slow full
    notification history scan (that was delaying delivery until session expiry).
    """
    uid = (user_id or '').strip()
    unique_tokens: List[str] = []
    seen: set[str] = set()
    for t in tokens or []:
        if isinstance(t, str) and t.strip() and t.strip() not in seen:
            seen.add(t.strip())
            unique_tokens.append(t.strip())

    if not unique_tokens:
        return {'success': False, 'error': 'NO_TOKEN', 'success_count': 0, 'failed_tokens': []}

    payload = dict(data or {})
    inbox_type = payload.get('type') or payload.get('notificationType') or 'system'
    will_store = store_inbox and uid and not _is_truthy(payload.get('notification_stored'))

    unseen_before = count_unseen_notifications(db, uid) if uid else 0
    badge_count = max(1, unseen_before + (1 if will_store else 0))

    if will_store:
        stored = store_inbox_notification(
            db,
            user_id=uid,
            title=title,
            body=body,
            type_value=str(inbox_type),
            data=payload,
        )
        payload['notification_stored'] = 'true'
        payload['delivery_id'] = stored['delivery_id']
        payload['type'] = normalize_notification_type(str(inbox_type))

    payload.setdefault('sound', PUSH_SOUND_ANDROID)
    payload.setdefault('channel_id', PUSH_CHANNEL_ID)
    payload.setdefault('deliver_immediately', 'true')

    success_count = 0
    failed_tokens: List[str] = []
    last_error: Optional[str] = None
    last_message_id: Optional[str] = None

    for token in unique_tokens:
        try:
            message = build_fcm_message(
                token=token,
                title=title,
                body=body,
                data=payload,
                badge_count=badge_count,
            )
            last_message_id = messaging.send(message)
            success_count += 1
        except Exception as exc:
            last_error = str(exc)
            logger.error('FCM Error for token %s...: %s', token[:12], exc)
            err_name = type(exc).__name__
            if err_name in (
                'UnregisteredError',
                'SenderIdMismatchError',
                'InvalidArgumentError',
            ):
                failed_tokens.append(token)

    return {
        'success': success_count > 0,
        'success_count': success_count,
        'failed_tokens': failed_tokens,
        'last_error': last_error,
        'message_id': last_message_id,
        'badge_count': badge_count,
    }


def send_fcm_to_token(
    *,
    title: str,
    body: str,
    token: str,
    data: Optional[Dict[str, Any]] = None,
    badge_count: int = 1,
) -> str:
    """Send one FCM message to a device token (no Firestore inbox)."""
    message = build_fcm_message(
        token=token,
        title=title,
        body=body,
        data=data,
        badge_count=badge_count,
    )
    return messaging.send(message)
