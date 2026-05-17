"""FCM push helpers with explicit APNs alert + sound for iOS."""

from firebase_admin import messaging

_IOS_APNS_HEADERS = {
    'apns-priority': '10',
    'apns-push-type': 'alert',
}


def build_fcm_message(*, title, body, token, data=None, sound='default'):
    """
    Build a cross-platform FCM message.

    iOS often shows a silent banner when only ``notification`` is set; include
    ``apns.payload.aps.sound`` so alerts play the system default tone.
    """
    notification = messaging.Notification(title=title, body=body)
    apns = messaging.APNSConfig(
        headers=dict(_IOS_APNS_HEADERS),
        payload=messaging.APNSPayload(
            aps=messaging.Aps(
                alert=messaging.ApsAlert(title=title, body=body),
                sound=sound,
                badge=1,
                custom_data={'interruption-level': 'active'},
            ),
        ),
    )
    kwargs = {
        'notification': notification,
        'apns': apns,
        'token': token,
    }
    merged_data = {k: str(v) for k, v in (data or {}).items()}
    merged_data.setdefault('sound', sound)
    kwargs['data'] = merged_data
    return messaging.Message(**kwargs)


def send_fcm_to_token(*, title, body, token, data=None, sound='default'):
    """Send one FCM message to a device token."""
    messaging.send(
        build_fcm_message(
            title=title,
            body=body,
            token=token,
            data=data,
            sound=sound,
        )
    )
