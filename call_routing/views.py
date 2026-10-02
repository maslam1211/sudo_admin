"""PBX call-bridge HTTP handlers (/admin/api/call/*)."""

import json
import logging
import secrets
import urllib.error
import urllib.request

from django.conf import settings
from django.http import JsonResponse
from django.utils.timezone import now
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from admin_app.models import CallRouteIntent

from .constants import (
    CALL_ROUTE_COMPANY_NUMBER_MISSING,
    CALL_ROUTE_INTENT_TTL_SEC,
    CALL_ROUTE_INVALID_FROM,
    CALL_ROUTING_EXPECTED_DID,
)

logger = logging.getLogger(__name__)


def _call_route_norm10(value):
    """
    Exactly 10 digits after optional leading 91 (12+ digits) or one leading 0 (11 digits).
    Never truncates arbitrary long input with last-10 slicing.
    """
    digits = ''.join(c for c in str(value or '') if c.isdigit())
    if len(digits) >= 12 and digits.startswith('91'):
        digits = digits[2:]
    if len(digits) == 11 and digits.startswith('0'):
        digits = digits[1:]
    if len(digits) != 10 or not digits.isdigit():
        return ''
    return digits


def _configured_company_caller_key():
    """10-digit COMPANY_PHONE_NUMBER, or '' when unset or invalid."""
    raw = getattr(settings, 'COMPANY_PHONE_NUMBER', '') or ''
    return _call_route_norm10(raw)


def _fresh_call_route_intent(key):
    """
    Non-expired CallRouteIntent for this caller key.
    Deletes the row when it is past the TTL.
    """
    if len(key) != 10:
        return None
    intent = CallRouteIntent.objects.filter(caller_key=key).first()
    if not intent:
        return None
    age_sec = (now() - intent.created_at).total_seconds()
    if age_sec <= CALL_ROUTE_INTENT_TTL_SEC:
        logger.info(
            'call_route webhook lookup caller_key=%s destination=%s age_sec=%.0f',
            key,
            intent.destination.strip(),
            age_sec,
        )
        return intent
    intent.delete()
    logger.warning(
        'call_route webhook expired caller_key=%s age_sec=%.0f ttl=%s',
        key,
        age_sec,
        CALL_ROUTE_INTENT_TTL_SEC,
    )
    return None


def _call_route_parse_json(request):
    try:
        return json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return None


def _provided_call_routing_api_key(request):
    auth = request.headers.get('Authorization') or request.META.get('HTTP_AUTHORIZATION', '')
    if isinstance(auth, str) and auth.lower().startswith('bearer '):
        return auth[7:].strip()
    return (
        request.headers.get('X-API-Key')
        or request.META.get('HTTP_X_API_KEY')
        or ''
    )


def _reject_bad_call_routing_api_key(request):
    """When CALL_ROUTING_API_KEY is set, webhook must send Bearer or X-API-Key."""
    expected = getattr(settings, 'CALL_ROUTING_API_KEY', '') or ''
    if not expected:
        return None
    got = _provided_call_routing_api_key(request)
    if len(got) != len(expected) or not secrets.compare_digest(
        got.encode('utf-8'), expected.encode('utf-8')
    ):
        return JsonResponse({'error': 'Unauthorized'}, status=401)
    return None


def _vehicle_scan_destination(db, qr_id, target):
    """Owner or emergency number for a vehicle sticker when the page omits destination."""
    try:
        qr_doc = db.collection('qrcodes').document(qr_id).get()
    except Exception:
        return ''
    if not qr_doc.exists:
        return ''
    qr_data = qr_doc.to_dict() or {}
    if not qr_data.get('isAssigned'):
        return ''
    vehicle_id = qr_data.get('vehicleID')
    if not vehicle_id:
        return ''
    try:
        vehicle_doc = db.collection('vehicles').document(vehicle_id).get()
    except Exception:
        return ''
    if not vehicle_doc.exists:
        return ''
    vehicle_data = vehicle_doc.to_dict() or {}
    owner_id = vehicle_data.get('ownerId')
    if not owner_id:
        return ''
    try:
        user_doc = db.collection('users').document(owner_id).get()
    except Exception:
        return ''
    if not user_doc.exists:
        return ''
    user_data = user_doc.to_dict() or {}
    if target == 'emergency':
        from admin_app.scanner_contact_prefs import normalize_phone_digits
        return normalize_phone_digits(user_data.get('defaultEmergencyContact', '')) or ''
    from admin_app.family_assignment import effective_contact_number
    return effective_contact_number(vehicle_data, user_data) or ''


def _mirror_multipurpose_register_to_live_gateway(request, destination, qr_id):
    """
    The phone line asks sudotag.com for the destination. A register stored only
    on this machine never reaches that lookup. Forward the same payload when
    this request is not already on the live host.
    Returns (status, body) or None when no forward is needed.
    """
    host = (request.get_host() or '').split(':')[0].lower()
    if host in ('sudotag.com', 'www.sudotag.com'):
        return None
    live = str(getattr(settings, 'BASE_DOMAIN', 'https://sudotag.com') or '').rstrip('/')
    if not live:
        return None
    payload = json.dumps({
        'destination': destination,
        'qr_id': qr_id,
        'target': 'owner',
    }).encode('utf-8')
    req = urllib.request.Request(
        f'{live}/admin/api/call/register',
        data=payload,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            return resp.status, resp.read().decode('utf-8', errors='replace')
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode('utf-8', errors='replace')
    except Exception as exc:
        logger.warning('call_route live gateway mirror failed: %s', exc)
        return 502, json.dumps({'error': 'Call gateway unavailable'})


@csrf_exempt
@require_POST
def register_call_destination(request):
    body = _call_route_parse_json(request)
    if body is None:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    phone_raw = body.get('from')
    explicit_from = str(phone_raw or '').strip() != ''
    phone = str(phone_raw or '').strip()
    destination = str(body.get('destination') or '').strip()
    qr_id = str(body.get('qr_id') or body.get('qrId') or '').strip()
    if not explicit_from:
        phone = str(getattr(settings, 'COMPANY_PHONE_NUMBER', '') or '').strip()
        if not phone:
            return JsonResponse({'error': CALL_ROUTE_COMPANY_NUMBER_MISSING}, status=500)

    key = _call_route_norm10(phone)
    if len(key) != 10:
        if explicit_from:
            return JsonResponse({'error': CALL_ROUTE_INVALID_FROM}, status=400)
        return JsonResponse({'error': CALL_ROUTE_COMPANY_NUMBER_MISSING}, status=500)

    try:
        # Lazy import: Firebase Admin is initialized in admin_app.views
        from admin_app.views import db
        from admin_app.scanner_contact_prefs import (
            send_scanner_voice_call_attempt_push,
            validate_scanner_call_for_qr,
        )
        from admin_app.scanner_notify_session_controls import (
            is_notify_sheet_done,
            touch_notify_active_session,
            voice_register_maybe_block,
            voice_register_record_success,
        )
    except Exception as exc:
        logger.exception('call_route register deps: %s', exc)
        return JsonResponse({'error': 'Server misconfigured'}, status=500)

    mp_data = None
    if qr_id:
        try:
            mp_snap = db.collection('multipurpose_qrs').document(qr_id).get()
            loaded = mp_snap.to_dict() if mp_snap.exists else None
        except Exception:
            loaded = None
        if (
            loaded
            and loaded.get('purpose') == 'multipurpose'
            and loaded.get('isAssigned')
        ):
            mp_data = loaded
    if not destination and mp_data:
        destination = str(mp_data.get('contactNumber') or '').strip()
    if not destination and qr_id and not mp_data:
        destination = _vehicle_scan_destination(
            db,
            qr_id,
            str(body.get('target') or 'owner').strip().lower(),
        )
    if not destination:
        return JsonResponse(
            {'error': 'from and destination required' if explicit_from else 'destination required'},
            status=400,
        )
    dest_key = _call_route_norm10(destination)
    if len(dest_key) != 10:
        return JsonResponse({'error': 'Invalid destination'}, status=400)

    block = voice_register_maybe_block(request, qr_id, key)
    if block is not None:
        return block

    if qr_id and not mp_data and is_notify_sheet_done(request, qr_id):
        return JsonResponse(
            {
                'status': 'error',
                'error_type': 'notify_session_expired',
                'message': (
                    'Session expired. Please rescan the QR code to continue.'
                ),
            },
            status=410,
        )

    if mp_data:
        stored = _call_route_norm10(mp_data.get('contactNumber'))
        if not stored or stored != dest_key:
            return JsonResponse(
                {
                    'status': 'error',
                    'error': 'This multipurpose QR has no matching contact number.',
                    'message': 'This multipurpose QR has no matching contact number.',
                },
                status=400,
            )
        policy_err = None
        try:
            from admin_app.views import sync_multipurpose_voice_bridge
            sync_multipurpose_voice_bridge(qr_id, mp_data)
        except Exception:
            logger.exception('call_route multipurpose voice bridge sync failed')
    else:
        policy_err = validate_scanner_call_for_qr(db, qr_id, dest_key)
    if policy_err:
        return JsonResponse(
            {'status': 'error', 'error': policy_err, 'message': policy_err},
            status=400,
        )

    if mp_data:
        mirrored = _mirror_multipurpose_register_to_live_gateway(request, dest_key, qr_id)
        if mirrored is not None:
            status_code, raw = mirrored
            if status_code < 200 or status_code >= 300:
                logger.warning(
                    'call_route live gateway rejected multipurpose qr_id=%s status=%s body=%s',
                    qr_id,
                    status_code,
                    raw[:300],
                )
                try:
                    parsed = json.loads(raw or '{}')
                except json.JSONDecodeError:
                    parsed = {}
                message = (
                    parsed.get('message')
                    or parsed.get('error')
                    or 'Could not register the call.'
                )
                return JsonResponse(
                    {'status': 'error', 'error': message, 'message': message},
                    status=400 if status_code < 500 else 502,
                )

    CallRouteIntent.objects.update_or_create(
        caller_key=key,
        defaults={'destination': destination},
    )
    logger.info('call_route register stored caller_key=%s destination=%s', key, destination)
    try:
        if not mp_data:
            send_scanner_voice_call_attempt_push(db, qr_id, dest_key, key)
    except Exception as exc:
        logger.warning('call_route register owner push alert failed: %s', exc)
    try:
        # Refresh the Contact Owner visit window so the user stays on this page
        # (and QR reload continues here). Soft idle wrap-up is client-driven.
        started_cd = voice_register_record_success(request, qr_id, key)
        session_meta = touch_notify_active_session(request, qr_id)
    except Exception as exc:
        logger.warning('call_route session throttle failed: %s', exc)
        started_cd = None
        session_meta = None
    payload = {'status': 'ok', 'redirect_home': False}
    if session_meta:
        payload['session_ttl_sec'] = session_meta['session_ttl_sec']
        payload['session_expires_at'] = session_meta['session_expires_at']
    if started_cd:
        payload['cooldown_seconds_remaining'] = int(started_cd)
        payload['voice_call_waiting'] = True
    return JsonResponse(payload)


@csrf_exempt
@require_POST
def api_call_webhook(request):
    denied = _reject_bad_call_routing_api_key(request)
    if denied:
        return denied

    body = _call_route_parse_json(request)
    if body is None:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    did = str(body.get('did') or '').strip()
    caller = str(body.get('from') or '').strip()
    if not caller:
        return JsonResponse({'error': 'Missing from'}, status=400)
    if _call_route_norm10(did) != _call_route_norm10(CALL_ROUTING_EXPECTED_DID):
        logger.warning('call_route webhook invalid did=%r expected=%s', did, CALL_ROUTING_EXPECTED_DID)
        return JsonResponse({'error': 'Invalid did'}, status=400)

    key = _call_route_norm10(caller)
    if len(key) != 10:
        return JsonResponse({'error': CALL_ROUTE_INVALID_FROM}, status=400)

    intent = _fresh_call_route_intent(key)
    if intent is None:
        company_key = _configured_company_caller_key()
        if company_key and company_key != key:
            intent = _fresh_call_route_intent(company_key)
            if intent is not None:
                logger.info(
                    'call_route webhook company fallback caller_key=%s',
                    company_key,
                )
    if intent is None:
        logger.warning(
            'call_route webhook miss caller_key=%s from_raw=%s — register POST /admin/api/call/register first',
            key,
            caller,
        )
        destination = ''
    else:
        destination = intent.destination.strip()

    if not destination:
        return JsonResponse({'error': 'No destination'}, status=400)

    logger.info('api_call_webhook ok from=%s destination=%s', caller, destination)

    return JsonResponse(
        {'status': '1', 'destination': destination},
        content_type='application/json; charset=utf-8',
    )
