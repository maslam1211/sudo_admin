"""PBX call-bridge HTTP handlers (/admin/api/call/*)."""

import json
import logging

from django.http import JsonResponse
from django.utils.timezone import now
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from admin_app.models import CallRouteIntent

from .constants import (
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


def _call_route_parse_json(request):
    try:
        return json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return None


@csrf_exempt
@require_POST
def register_call_destination(request):
    body = _call_route_parse_json(request)
    if body is None:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    phone = str(body.get('from') or '').strip()
    destination = str(body.get('destination') or '').strip()
    if not phone or not destination:
        return JsonResponse({'error': 'from and destination required'}, status=400)

    key = _call_route_norm10(phone)
    if len(key) != 10:
        return JsonResponse({'error': CALL_ROUTE_INVALID_FROM}, status=400)

    CallRouteIntent.objects.update_or_create(
        caller_key=key,
        defaults={'destination': destination},
    )
    logger.info('call_route register stored caller_key=%s destination=%s', key, destination)
    return JsonResponse({'status': 'ok'})


@csrf_exempt
@require_POST
def api_call_webhook(request):
    body = _call_route_parse_json(request)
    if body is None:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    did = str(body.get('did') or '').strip()
    caller = str(body.get('from') or '').strip()
    if not caller:
        return JsonResponse({'error': 'Missing from'}, status=400)
    if did != CALL_ROUTING_EXPECTED_DID:
        return JsonResponse({'error': 'Invalid did'}, status=400)

    key = _call_route_norm10(caller)
    if len(key) != 10:
        return JsonResponse({'error': CALL_ROUTE_INVALID_FROM}, status=400)

    destination = ''
    intent = CallRouteIntent.objects.filter(caller_key=key).first()
    if intent:
        age_sec = (now() - intent.created_at).total_seconds()
        if age_sec <= CALL_ROUTE_INTENT_TTL_SEC:
            destination = intent.destination.strip()
            logger.info(
                'call_route webhook lookup caller_key=%s destination=%s age_sec=%.0f',
                key,
                destination,
                age_sec,
            )
        else:
            intent.delete()
            logger.warning(
                'call_route webhook expired caller_key=%s age_sec=%.0f ttl=%s',
                key,
                age_sec,
                CALL_ROUTE_INTENT_TTL_SEC,
            )
    else:
        logger.warning(
            'call_route webhook miss caller_key=%s from_raw=%s — register POST /admin/api/call/register first',
            key,
            caller,
        )

    if not destination:
        return JsonResponse({'error': 'No destination'}, status=400)

    logger.info('api_call_webhook ok from=%s destination=%s', caller, destination)

    return JsonResponse(
        {'status': '1', 'destination': destination},
        content_type='application/json; charset=utf-8',
    )
