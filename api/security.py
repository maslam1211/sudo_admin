"""Who is calling: Firebase ID token, App Check token, client IP."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.conf import settings
from ninja.security import HttpBearer

from . import firebase
from .errors import ApiError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Caller:
    uid: str
    phone_number: str  # E.164 from the token, '' when the account has none
    claims: dict


class FirebaseBearer(HttpBearer):
    """`Authorization: Bearer <Firebase ID token>`. Sets request.auth to a Caller."""

    def authenticate(self, request, token):
        token = (token or '').strip()
        if not token:
            return None
        try:
            claims = firebase.verify_id_token(token)
        except Exception as exc:  # expired, revoked, wrong project, malformed
            logger.info('API: rejected ID token (%s)', type(exc).__name__)
            return None
        uid = str(claims.get('uid') or claims.get('sub') or '').strip()
        if not uid:
            return None
        caller = Caller(uid=uid, phone_number=str(claims.get('phone_number') or ''), claims=claims)
        request.caller = caller
        return caller


firebase_auth = FirebaseBearer()


def client_ip(request) -> str:
    """Client address for rate limits.

    Behind nginx (`proxy_add_x_forwarded_for`) the **last** X-Forwarded-For
    entry is the one nginx appended; earlier entries come from the client and
    can be forged, so they are ignored.
    """
    if getattr(settings, 'API_TRUST_X_FORWARDED_FOR', True):
        real_ip = (request.META.get('HTTP_X_REAL_IP') or '').strip()
        if real_ip:
            return real_ip
        forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
        if forwarded:
            return forwarded.split(',')[-1].strip()
    return request.META.get('REMOTE_ADDR', '') or ''


def check_app_check(request) -> None:
    """Verify `X-Firebase-AppCheck` when sent; require it when API_REQUIRE_APP_CHECK.

    Off by default: App Check has never been enforced for SudoTag, and old
    builds or emulators without a valid token must keep working until it is
    switched on deliberately.
    """
    token = (request.headers.get('X-Firebase-AppCheck') or '').strip()
    required = bool(getattr(settings, 'API_REQUIRE_APP_CHECK', False))
    if not token:
        if required:
            raise ApiError('unauthenticated', 'Please update SudoTag and try again.')
        return
    try:
        firebase.verify_app_check_token(token)
    except Exception as exc:
        logger.info('API: rejected App Check token (%s)', type(exc).__name__)
        if required:
            raise ApiError('unauthenticated', 'Please update SudoTag and try again.')
