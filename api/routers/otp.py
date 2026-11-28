"""Phone OTP over MSG91, done on the server.

Replaces the app's direct MSG91 calls (lib/service/msg91_otp_service.dart,
which shipped the MSG91 auth key inside the app) and the Cloud Function
`verifyMsg91OtpAndGetToken`.

    POST /api/v1/auth/otp/send     {phone}            public
    POST /api/v1/auth/otp/resend   {phone}            public
    POST /api/v1/auth/otp/verify   {phone, otp}       public -> {customToken}
    POST /api/v1/phone/otp/verify  {phone, otp}       signed in -> {verified}
"""

from __future__ import annotations

import logging
from urllib.parse import quote

import requests
from ninja import Router, Schema

from admin_app import msg91_otp

from .. import firebase, ratelimit
from ..errors import ApiError
from ..security import check_app_check, client_ip, firebase_auth

logger = logging.getLogger(__name__)

public_router = Router(tags=['auth'])
phone_router = Router(tags=['phone'], auth=firebase_auth)

SEND_PER_PHONE_15MIN = 5
SEND_PER_PHONE_DAY = 10
SEND_PER_IP_HOUR = 20
VERIFY_PER_PHONE_15MIN = 8
VERIFY_PER_UID_15MIN = 10


class PhoneIn(Schema):
    phone: str


class PhoneOtpIn(Schema):
    phone: str
    otp: str


class SentOut(Schema):
    sent: bool


class CustomTokenOut(Schema):
    customToken: str


class VerifiedOut(Schema):
    verified: bool
    phone: str  # 10-digit national form, as stored in users.contactNumber


def _e164(raw: str) -> str:
    error, e164 = msg91_otp.phone_to_msg91_e164(raw)
    if error:
        raise ApiError('invalid-argument', error)
    return e164


def _otp_code(raw: str) -> str:
    code = ''.join(c for c in str(raw or '') if c.isdigit())
    if not 4 <= len(code) <= 8:
        raise ApiError('invalid-argument', 'Enter the code from the SMS.')
    return code


def _limit_send(request, phone: str) -> None:
    ratelimit.hit(f'otp-send:phone15:{phone}', limit=SEND_PER_PHONE_15MIN, window_seconds=15 * 60,
                  message='Too many codes sent to this number. Try again in 15 minutes.')
    ratelimit.hit(f'otp-send:phoneday:{phone}', limit=SEND_PER_PHONE_DAY, window_seconds=24 * 3600,
                  message='Too many codes sent to this number today. Try again tomorrow.')
    ip = client_ip(request)
    if ip:
        ratelimit.hit(f'otp-send:ip:{ip}', limit=SEND_PER_IP_HOUR, window_seconds=3600)


def _send(phone: str) -> None:
    try:
        msg91_otp.send_otp(phone)
    except msg91_otp.Msg91OtpError as exc:
        logger.warning('OTP send failed for ***%s: %s', phone[-4:], exc)
        raise ApiError('unavailable', "Couldn't send the code. Please try again.")
    except requests.RequestException:
        raise ApiError('unavailable', "Couldn't reach the SMS service. Please try again.")


def _resend(phone: str) -> None:
    """MSG91 retry first; a fresh send only if the retry is refused.

    Sending both (as admin_app.msg91_otp.resend_otp does for the web) gives the
    user two different codes, and the first to arrive is already invalid.
    """
    auth_key = msg91_otp.msg91_auth_key()
    if not auth_key:
        raise ApiError('unavailable', "Couldn't send the code. Please try again.")
    mobile = ''.join(c for c in phone if c.isdigit())
    url = (f'{msg91_otp.MSG91_OTP_BASE_URL}/retry?authkey={quote(auth_key, safe="")}'
           f'&retrytype=text&mobile={quote(mobile, safe="")}')
    try:
        response = requests.get(url, timeout=20)
        if response.status_code == 200 and (response.json() or {}).get('type') == 'success':
            return
    except (requests.RequestException, ValueError):
        pass
    _send(phone)


def _verify_with_msg91(phone: str, code: str) -> None:
    try:
        msg91_otp.verify_otp(phone, code)
    except msg91_otp.Msg91OtpError as exc:
        message = str(exc) or 'Incorrect code. Please try again.'
        if message.startswith('HTTP '):
            raise ApiError('unavailable', "Couldn't check the code. Please try again.")
        raise ApiError('invalid-argument', message)
    except requests.RequestException:
        raise ApiError('unavailable', "Couldn't reach the SMS service. Please try again.")


def resolve_uid_for_phone(phone_e164: str) -> str:
    """Same account resolution as the `verifyMsg91OtpAndGetToken` function.

    1. A Firebase Auth user with this phone number.
    2. Else a SudoTag profile (users.contactNumber) with this number — link the
       phone to that Auth user, creating the Auth record under the same uid if
       it is missing. Avoids a second, empty account for Google/email users.
    3. Else a brand-new Auth user.
    """
    auth = firebase.auth_module()
    try:
        return auth.get_user_by_phone_number(phone_e164).uid
    except auth.UserNotFoundError:
        pass

    national = ''.join(c for c in phone_e164 if c.isdigit())[-10:]
    profile_uid = None
    if len(national) == 10:
        docs = list(
            firebase.firestore_db().collection('users')
            .where('contactNumber', '==', national).limit(1).stream()
        )
        if docs:
            profile_uid = docs[0].id

    if not profile_uid:
        return auth.create_user(phone_number=phone_e164).uid

    try:
        auth.get_user(profile_uid)
    except auth.UserNotFoundError:
        auth.create_user(uid=profile_uid, phone_number=phone_e164)
        return profile_uid
    try:
        auth.update_user(profile_uid, phone_number=phone_e164)
    except Exception as exc:  # number already on another Auth user, etc.
        logger.warning('Could not link phone to uid %s: %s', profile_uid, exc)
    return profile_uid


@public_router.post('/otp/send', response=SentOut)
def otp_send(request, body: PhoneIn):
    check_app_check(request)
    phone = _e164(body.phone)
    _limit_send(request, phone)
    _send(phone)
    return {'sent': True}


@public_router.post('/otp/resend', response=SentOut)
def otp_resend(request, body: PhoneIn):
    check_app_check(request)
    phone = _e164(body.phone)
    _limit_send(request, phone)
    _resend(phone)
    return {'sent': True}


@public_router.post('/otp/verify', response=CustomTokenOut)
def otp_verify(request, body: PhoneOtpIn):
    check_app_check(request)
    phone = _e164(body.phone)
    code = _otp_code(body.otp)
    ratelimit.hit(f'otp-verify:phone:{phone}', limit=VERIFY_PER_PHONE_15MIN, window_seconds=15 * 60,
                  message='Too many wrong codes. Request a new code in 15 minutes.')
    _verify_with_msg91(phone, code)
    try:
        uid = resolve_uid_for_phone(phone)
        token = firebase.auth_module().create_custom_token(uid)
    except ApiError:
        raise
    except Exception as exc:
        logger.exception('OTP login: could not issue token: %s', exc)
        raise ApiError('internal', 'Sign-in failed. Please try again.')
    if isinstance(token, bytes):
        token = token.decode('utf-8')
    from accounts import service as accounts_service

    accounts_service.record_verified_phone(firebase.firestore_db(), uid, phone)
    return {'customToken': token}


@phone_router.post('/otp/verify', response=VerifiedOut)
def phone_otp_verify(request, body: PhoneOtpIn):
    """Checks a code for a number without signing in (profile, family, transfer, PIN reset)."""
    phone = _e164(body.phone)
    code = _otp_code(body.otp)
    ratelimit.hit(f'phone-verify:uid:{request.auth.uid}', limit=VERIFY_PER_UID_15MIN, window_seconds=15 * 60,
                  message='Too many wrong codes. Request a new code in 15 minutes.')
    ratelimit.hit(f'otp-verify:phone:{phone}', limit=VERIFY_PER_PHONE_15MIN, window_seconds=15 * 60,
                  message='Too many wrong codes. Request a new code in 15 minutes.')
    _verify_with_msg91(phone, code)
    return {'verified': True, 'phone': phone[-10:]}
