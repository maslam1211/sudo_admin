"""Admin settings for the in-app promotion notification stored in Firestore."""

from __future__ import annotations

import logging

from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods
from firebase_admin import firestore

from .fcm_push import send_push_to_user
from .scheduled_push import (
    INTERVAL_CHOICES,
    cancel_schedule,
    create_schedule,
    list_schedules,
    parse_local_datetime,
    resolve_user,
)

logger = logging.getLogger(__name__)

COLLECTION = 'app_settings'
DOCUMENT_ID = 'promotion_notification'

DEFAULTS = {
    'enabled': False,
    'title': '',
    'message': '',
    'imageUrl': '',
    'linkUrl': '',
    'buttonText': 'Open',
}


def _get_db():
    from .views import db
    return db


def _require_admin(request):
    if not request.session.get('admin'):
        messages.error(request, 'Admin access required')
        return redirect('admin_login')
    return None


def _text(raw, limit: int) -> str:
    return str(raw or '').strip()[:limit]


def get_promotion_notification(db) -> dict:
    data = {}
    try:
        snap = db.collection(COLLECTION).document(DOCUMENT_ID).get()
        if snap.exists:
            data = snap.to_dict() or {}
    except Exception as exc:
        logger.warning('promotion notification read failed: %s', exc)
        data = {}
    settings = dict(DEFAULTS)
    settings['enabled'] = bool(data.get('enabled'))
    for key, limit in (
        ('title', 80),
        ('message', 240),
        ('imageUrl', 500),
        ('linkUrl', 500),
        ('buttonText', 40),
    ):
        value = _text(data.get(key), limit)
        if value or key != 'buttonText':
            settings[key] = value or DEFAULTS[key]
    return settings


def save_promotion_notification(db, settings: dict) -> dict:
    payload = {
        'enabled': bool(settings.get('enabled')),
        'title': _text(settings.get('title'), 80),
        'message': _text(settings.get('message'), 240),
        'imageUrl': _text(settings.get('imageUrl'), 500),
        'linkUrl': _text(settings.get('linkUrl'), 500),
        'buttonText': _text(settings.get('buttonText'), 40) or 'Open',
        'updatedAt': firestore.SERVER_TIMESTAMP,
    }
    db.collection(COLLECTION).document(DOCUMENT_ID).set(payload, merge=True)
    return get_promotion_notification(db)


def clear_promotion_form(db) -> None:
    """Blank the compose fields after a successful send or schedule."""
    save_promotion_notification(
        db,
        {
            'enabled': False,
            'title': '',
            'message': '',
            'imageUrl': '',
            'linkUrl': '',
            'buttonText': 'Open',
        },
    )


def customer_fcm_targets(db) -> list[tuple[str, str]]:
    """Every customer user id that has an FCM device token."""
    targets: list[tuple[str, str]] = []
    seen: set[str] = set()
    for doc in db.collection('users').select(['fcmToken']).stream():
        token = str((doc.to_dict() or {}).get('fcmToken') or '').strip()
        if not token or token in seen:
            continue
        seen.add(token)
        targets.append((doc.id, token))
    return targets


def send_promotion_to_customers(db, settings: dict) -> dict:
    """Push the promotion to each customer's FCM token and store it in their inbox."""
    from firebase_admin import messaging

    from .fcm_push import build_fcm_message, store_inbox_notification

    title = _text(settings.get('title'), 80)
    body = _text(settings.get('message'), 240)
    targets = customer_fcm_targets(db)
    sent = 0
    failed = 0
    base = {
        'type': 'promotion',
        'notificationType': 'promotion',
        'linkUrl': _text(settings.get('linkUrl'), 500),
        'imageUrl': _text(settings.get('imageUrl'), 500),
        'buttonText': _text(settings.get('buttonText'), 40) or 'Open',
    }
    step = 400
    for start in range(0, len(targets), step):
        chunk = targets[start:start + step]
        messages = []
        for user_id, token in chunk:
            stored = store_inbox_notification(
                db,
                user_id=user_id,
                title=title,
                body=body,
                type_value='promotion',
                data=base,
            )
            payload = {
                **base,
                'notification_stored': 'true',
                'delivery_id': stored['delivery_id'],
            }
            messages.append(
                build_fcm_message(
                    token=token,
                    title=title,
                    body=body,
                    data=payload,
                    badge_count=1,
                )
            )
        result = messaging.send_each(messages)
        sent += int(result.success_count or 0)
        failed += int(result.failure_count or 0)
    db.collection(COLLECTION).document(DOCUMENT_ID).set(
        {
            'lastSentAt': firestore.SERVER_TIMESTAMP,
            'lastSentCount': sent,
            'lastFailedCount': failed,
            'lastTargetCount': len(targets),
        },
        merge=True,
    )
    return {'targets': len(targets), 'sent': sent, 'failed': failed}


@require_http_methods(['GET', 'POST'])
def manage_promotion_notification(request):
    """Set the promotion card the SudoTag app reads from Firestore."""
    gate = _require_admin(request)
    if gate:
        return gate

    db = _get_db()
    if request.method == 'POST' and request.POST.get('action') == 'schedule_cancel':
        cancel_schedule(db, _text(request.POST.get('schedule_id'), 80))
        messages.success(request, 'Scheduled push stopped.')
        return redirect('manage_promotion_notification')
    if request.method == 'POST' and request.POST.get('action') in ('send_user', 'schedule_user'):
        return _handle_user_push(request, db)
    if request.method == 'POST':
        settings = {
            'enabled': request.POST.get('enabled') == 'on',
            'title': _text(request.POST.get('title'), 80),
            'message': _text(request.POST.get('message'), 240),
            'imageUrl': _text(request.POST.get('imageUrl'), 500),
            'linkUrl': _text(request.POST.get('linkUrl'), 500),
            'buttonText': _text(request.POST.get('buttonText'), 40) or 'Open',
        }
        if not settings['title'] or not settings['message']:
            messages.error(request, 'Add a title and message before saving or sending.')
        else:
            action = request.POST.get('action') or 'save'
            try:
                if action == 'schedule_all':
                    _schedule_all_customers(request, db, settings)
                elif action == 'send':
                    result = send_promotion_to_customers(db, settings)
                    clear_promotion_form(db)
                    messages.success(
                        request,
                        f"Sent to {result['sent']} of {result['targets']} customers with an FCM token."
                        + (f" {result['failed']} could not be delivered." if result['failed'] else ''),
                    )
                else:
                    save_promotion_notification(db, settings)
                    messages.success(
                        request,
                        'Promotion notification saved in Firebase. Use Send to deliver it to every customer with an FCM token.',
                    )
            except Exception as exc:
                logger.exception('promotion notification save failed: %s', exc)
                messages.error(request, f'Could not save the promotion notification: {exc}')
            else:
                return redirect('manage_promotion_notification')

    return render(
        request,
        'manage_promotion_notification.html',
        {
            'settings': get_promotion_notification(db),
            'schedules': list_schedules(db),
            'intervals': INTERVAL_CHOICES,
        },
    )


def _schedule_all_customers(request, db, settings):
    next_run = parse_local_datetime(request.POST.get('all_next_run') or '')
    end_at = parse_local_datetime(request.POST.get('all_end_at') or '')
    try:
        interval = int(request.POST.get('all_interval_minutes') or 0)
    except (TypeError, ValueError):
        interval = -1
    if next_run is None:
        messages.error(request, 'Choose the first send time for all customers.')
        return
    try:
        create_schedule(
            db,
            uid='',
            title=settings['title'],
            message=settings['message'],
            link_url=settings['linkUrl'],
            image_url=settings['imageUrl'],
            button_text=settings['buttonText'],
            next_run_at=next_run,
            interval_minutes=interval,
            end_at=end_at,
            audience='all',
        )
    except ValueError as exc:
        messages.error(request, str(exc))
        return
    clear_promotion_form(db)
    messages.success(
        request,
        'Scheduled for every customer with an FCM token. The form is cleared. It sends while this server is running.',
    )


def _customer_image_url(request) -> str:
    uploaded = request.FILES.get('user_image')
    if uploaded:
        content_type = str(getattr(uploaded, 'content_type', '') or '')
        if not content_type.startswith('image/'):
            raise ValueError('Choose an image file.')
        import cloudinary.uploader
        result = cloudinary.uploader.upload(
            uploaded,
            folder='sudotag/push',
            resource_type='image',
        )
        url = str(result.get('secure_url') or '').strip()
        if not url:
            raise ValueError('The image could not be uploaded.')
        return url[:500]
    return _text(request.POST.get('user_image_url'), 500)


def _handle_user_push(request, db):
    title = _text(request.POST.get('user_title'), 80)
    message = _text(request.POST.get('user_message'), 240)
    link_url = _text(request.POST.get('user_link'), 500)
    uid = resolve_user(db, request.POST.get('user_query') or '')
    action = request.POST.get('action')
    try:
        image_url = _customer_image_url(request)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect('manage_promotion_notification')
    except Exception as exc:
        logger.exception('customer push image upload failed: %s', exc)
        messages.error(request, 'The image could not be uploaded.')
        return redirect('manage_promotion_notification')
    if not uid:
        messages.error(request, 'No customer was found for that user ID or email.')
    elif not title or not message:
        messages.error(request, 'Add a title and message for this customer.')
    elif action == 'send_user':
        result = send_push_to_user(
            db,
            user_id=uid,
            title=title,
            body=message,
            data={
                'type': 'promotion',
                'notificationType': 'promotion',
                'linkUrl': link_url,
                'imageUrl': image_url,
            },
        )
        if result.get('success'):
            messages.success(request, 'Push notification sent to that customer.')
        elif result.get('error') == 'NO_TOKEN':
            messages.error(request, 'That customer has no FCM token, so the push cannot be delivered.')
        else:
            messages.error(request, 'The push could not be sent.')
    else:
        next_run = parse_local_datetime(request.POST.get('next_run') or '')
        end_at = parse_local_datetime(request.POST.get('end_at') or '')
        try:
            interval = int(request.POST.get('interval_minutes') or 0)
        except (TypeError, ValueError):
            interval = -1
        if next_run is None:
            messages.error(request, 'Choose the first send time.')
        else:
            try:
                create_schedule(
                    db,
                    uid=uid,
                    title=title,
                    message=message,
                    link_url=link_url,
                    image_url=image_url,
                    next_run_at=next_run,
                    interval_minutes=interval,
                    end_at=end_at,
                )
            except ValueError as exc:
                messages.error(request, str(exc))
            else:
                messages.success(request, 'Scheduled push saved. It sends while this server is running.')
    return redirect('manage_promotion_notification')
