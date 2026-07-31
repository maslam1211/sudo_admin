"""MSG91 campaign SMS for scanner vehicle-issue tips (manual + Lost Mode auto)."""

from __future__ import annotations

import logging
from typing import Any

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

MSG91_VEHICLE_ISSUE_CAMPAIGN_URL = (
    'https://control.msg91.com/api/v5/campaign/api/'
    'campaigns/sudotag-vehicle-issue-test/run'
)


def _auth_key() -> str:
    return (getattr(settings, 'MSG91_AUTH_KEY', '') or '').strip()


def _api_has_error(value: Any) -> bool:
    """MSG91 may return hasError as bool, int, or string."""
    if value is True or value == 1:
        return True
    if isinstance(value, str) and value.strip().lower() in ('true', '1', 'yes'):
        return True
    return False


def send_vehicle_issue_sms(
    *,
    digits_10: str,
    message: str,
    timeout: float = 15,
) -> dict[str, Any]:
    """
    Send the sudotag-vehicle-issue MSG91 campaign SMS.

    Returns ``{ok, error, api, http_status}``.
    """
    digits = ''.join(c for c in str(digits_10 or '') if c.isdigit())
    if len(digits) != 10:
        return {
            'ok': False,
            'error': 'invalid_phone',
            'api': None,
            'http_status': None,
        }

    text = (message or '').strip()
    if not text:
        text = 'Someone scanned your SUDO Tag.'
    # Campaign variable length limit.
    text = text[:200]

    authkey = _auth_key()
    if not authkey:
        return {
            'ok': False,
            'error': 'missing_auth_key',
            'api': None,
            'http_status': None,
        }

    formatted = '91' + digits
    headers = {
        'Content-Type': 'application/json',
        'authkey': authkey,
    }
    payload = {
        'data': {
            'sendTo': [
                {
                    'to': [
                        {
                            'mobiles': formatted,
                            'variables': {
                                'var': {
                                    'type': 'vehicle_issue',
                                    'value': text,
                                }
                            },
                        }
                    ],
                    'variables': {
                        'var': {
                            'type': 'vehicle_issue',
                            'value': text,
                        }
                    },
                }
            ]
        }
    }

    try:
        response = requests.post(
            MSG91_VEHICLE_ISSUE_CAMPAIGN_URL,
            json=payload,
            headers=headers,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        logger.warning('MSG91 vehicle SMS request failed: %s', exc)
        return {
            'ok': False,
            'error': f'request_failed:{exc}',
            'api': None,
            'http_status': None,
        }

    api: dict[str, Any] = {}
    try:
        if response.content:
            parsed = response.json()
            if isinstance(parsed, dict):
                api = parsed
    except ValueError:
        api = {'raw': (response.text or '')[:300]}

    http_status = response.status_code
    if http_status != 200:
        logger.warning(
            'MSG91 vehicle SMS HTTP %s: %s',
            http_status,
            (response.text or '')[:300],
        )
        return {
            'ok': False,
            'error': f'http_{http_status}',
            'api': api,
            'http_status': http_status,
        }

    if _api_has_error(api.get('hasError')):
        logger.warning('MSG91 vehicle SMS API error: %s', api)
        return {
            'ok': False,
            'error': str(api.get('message') or api.get('errors') or 'api_error'),
            'api': api,
            'http_status': http_status,
        }

    status_val = str(api.get('status') or api.get('type') or '').strip().lower()
    # Accept success / ok / omitted status when HTTP 200 and hasError is false.
    if status_val and status_val not in ('success', 'ok'):
        logger.warning('MSG91 vehicle SMS unexpected status: %s', api)
        return {
            'ok': False,
            'error': str(api.get('message') or status_val or 'api_error'),
            'api': api,
            'http_status': http_status,
        }

    logger.info('MSG91 vehicle SMS sent to ***%s', digits[-4:])
    return {
        'ok': True,
        'error': None,
        'api': api,
        'http_status': http_status,
    }
