"""MSG91 OTP send, resend, and verify — mirrors mobile app Msg91OtpService."""

import logging
from urllib.parse import quote

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

MSG91_OTP_BASE_URL = 'https://control.msg91.com/api/v5/otp'
ACTIVATE_OTP_SESSION_KEY = 'activate_otp_verified'


class Msg91OtpError(Exception):
    """Raised when MSG91 returns a non-success response."""


def msg91_auth_key():
    return getattr(settings, 'MSG91_AUTH_KEY', '') or ''


def msg91_otp_template_id():
    return getattr(settings, 'MSG91_OTP_TEMPLATE_ID', '') or ''


def _normalize_india_mobile_10(raw_contact):
    """Return 10-digit Indian mobile or None (same rules as views.normalize_phone_number)."""
    if raw_contact is None:
        return None
    digits = ''.join(c for c in str(raw_contact).strip() if c.isdigit())
    if not digits:
        return None
    if len(digits) >= 12 and digits.startswith('91'):
        digits = digits[2:]
    if len(digits) == 11 and digits.startswith('0'):
        digits = digits[1:]
    if len(digits) == 10 and digits.isdigit():
        return digits
    return None


def phone_to_msg91_e164(raw_contact):
    """
    Canonicalize to E.164 for MSG91 (+91 + 10 digits for India).
    Returns (error_message, e164_or_none).
    """
    digits = _normalize_india_mobile_10(raw_contact)
    if not digits:
        return 'Enter a valid 10-digit Indian mobile number', None
    return None, f'+91{digits}'


def _parse_msg91_response(response):
    if response.status_code != 200:
        raise Msg91OtpError(f'HTTP {response.status_code}: {response.text}')
    try:
        data = response.json()
    except (ValueError, TypeError) as exc:
        raise Msg91OtpError('Invalid response from OTP service.') from exc
    if not isinstance(data, dict):
        raise Msg91OtpError('Invalid response from OTP service.')
    return data


def send_otp(phone_e164):
    auth_key = msg91_auth_key()
    template_id = msg91_otp_template_id()
    if not auth_key or not template_id:
        raise Msg91OtpError('OTP service is not configured.')

    mobile_q = quote(phone_e164, safe='')
    url = (
        f'{MSG91_OTP_BASE_URL}?mobile={mobile_q}'
        f'&authkey={quote(auth_key, safe="")}'
        f'&template_id={quote(template_id, safe="")}'
    )
    response = requests.post(
        url,
        headers={'Content-Type': 'application/json'},
        json={'Param1': 'value1', 'Param2': 'value2', 'Param3': 'value3'},
        timeout=30,
    )
    data = _parse_msg91_response(response)
    if data.get('type') != 'success':
        raise Msg91OtpError(data.get('message') or 'Failed to send OTP.')
    logger.info('MSG91 OTP sent to %s', phone_e164[-4:].rjust(len(phone_e164), '*'))


def resend_otp(phone_e164):
    auth_key = msg91_auth_key()
    if not auth_key:
        raise Msg91OtpError('OTP service is not configured.')

    mobile_q = quote(phone_e164, safe='')
    retry_url = (
        f'{MSG91_OTP_BASE_URL}/retry?authkey={quote(auth_key, safe="")}'
        f'&retrytype=text&mobile={mobile_q}'
    )
    try:
        requests.get(retry_url, timeout=30)
    except requests.RequestException:
        pass

    send_otp(phone_e164)


def verify_otp(phone_e164, otp):
    auth_key = msg91_auth_key()
    if not auth_key:
        raise Msg91OtpError('OTP service is not configured.')

    otp_q = quote(str(otp).strip(), safe='')
    mobile_q = quote(phone_e164, safe='')
    url = f'{MSG91_OTP_BASE_URL}/verify?otp={otp_q}&mobile={mobile_q}'
    response = requests.get(url, headers={'authkey': auth_key}, timeout=30)
    data = _parse_msg91_response(response)
    if data.get('type') != 'success':
        raise Msg91OtpError(data.get('message') or 'OTP verification failed.')


def get_activate_otp_verified_map(request):
    return request.session.get(ACTIVATE_OTP_SESSION_KEY) or {}


def mark_activate_phone_verified(request, qr_id, phone_e164):
    verified = dict(get_activate_otp_verified_map(request))
    verified[str(qr_id)] = phone_e164
    request.session[ACTIVATE_OTP_SESSION_KEY] = verified
    request.session.modified = True


def clear_activate_phone_verified(request, qr_id):
    verified = dict(get_activate_otp_verified_map(request))
    if str(qr_id) in verified:
        del verified[str(qr_id)]
        request.session[ACTIVATE_OTP_SESSION_KEY] = verified
        request.session.modified = True


def is_activate_phone_verified(request, qr_id, phone_e164):
    return get_activate_otp_verified_map(request).get(str(qr_id)) == phone_e164
