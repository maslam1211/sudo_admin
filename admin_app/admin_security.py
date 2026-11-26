"""Admin sign-in security: personal passwords, authenticator-app codes (TOTP),
lockouts after wrong tries, session time limits and a sign-in history.

Firestore (server only; the mobile app's rules deny every client):
    admin_accounts/{uid}        passwordHash, encrypted TOTP secret, setup state
    admin_login_events/{auto}   one row per sign-in attempt that got past the PIN

The TOTP secret is encrypted with a key derived from ADMIN_2FA_KEY (or
SECRET_KEY when that is unset), so a database leak alone does not reveal it.
Codes follow RFC 6238 (30 s, 6 digits, SHA-1), which every authenticator app
on iPhone (Passwords, Google/Microsoft Authenticator, 1Password …) supports.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import logging
import secrets
import struct
import time
from typing import Optional
from urllib.parse import quote

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.cache import cache

logger = logging.getLogger(__name__)

ACCOUNTS = 'admin_accounts'
EVENTS = 'admin_login_events'
ISSUER = 'SudoTag Admin'
TOTP_PERIOD = 30
TOTP_DIGITS = 6
MIN_PASSWORD_LENGTH = 10

MAX_TRIES = 5
LOCK_SECONDS = 15 * 60
IDLE_SECONDS = 30 * 60
MAX_SESSION_SECONDS = 12 * 60 * 60
PENDING_SECONDS = 10 * 60  # password accepted, waiting for the code


class SecurityError(ValueError):
    """Message is safe to show on the page."""


# ─── TOTP (RFC 6238) ────────────────────────────────────────────────────────

def new_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode('ascii').rstrip('=')


def _b32decode(secret: str) -> bytes:
    s = secret.strip().replace(' ', '').upper()
    return base64.b32decode(s + '=' * (-len(s) % 8))


def totp_at(secret: str, step: int) -> str:
    digest = hmac.new(_b32decode(secret), struct.pack('>Q', step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack('>I', digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(code % (10 ** TOTP_DIGITS)).zfill(TOTP_DIGITS)


def current_step(now: Optional[float] = None) -> int:
    return int((time.time() if now is None else now) // TOTP_PERIOD)


def verify_totp(secret: str, code: str, *, now: Optional[float] = None, last_step: int = -1) -> Optional[int]:
    """Return the matching time step (±1 for clock drift), or None.
    Steps at or before `last_step` are refused so a code can't be reused."""
    code = ''.join(ch for ch in str(code or '') if ch.isdigit())
    if len(code) != TOTP_DIGITS or not secret:
        return None
    step = current_step(now)
    for s in (step - 1, step, step + 1):
        if s > last_step and hmac.compare_digest(totp_at(secret, s), code):
            return s
    return None


def otpauth_uri(secret: str, email: str) -> str:
    label = quote(f'{ISSUER}:{email}')
    return (f'otpauth://totp/{label}?secret={secret}&issuer={quote(ISSUER)}'
            f'&algorithm=SHA1&digits={TOTP_DIGITS}&period={TOTP_PERIOD}')


def qr_data_uri(text: str) -> str:
    import qrcode
    img = qrcode.make(text, box_size=6, border=2)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode('ascii')


def group_secret(secret: str) -> str:
    """'ABCD EFGH …' so it is easy to type by hand."""
    return ' '.join(secret[i:i + 4] for i in range(0, len(secret), 4))


# ─── Encryption of the TOTP secret ──────────────────────────────────────────

def _fernet():
    from cryptography.fernet import Fernet
    material = (getattr(settings, 'ADMIN_2FA_KEY', '') or settings.SECRET_KEY).encode('utf-8')
    key = base64.urlsafe_b64encode(hashlib.sha256(b'sudotag-admin-2fa|' + material).digest())
    return Fernet(key)


def encrypt(text: str) -> str:
    return _fernet().encrypt(text.encode('utf-8')).decode('ascii')


def decrypt(token: str) -> str:
    return _fernet().decrypt(token.encode('ascii')).decode('utf-8')


# ─── Passwords ──────────────────────────────────────────────────────────────

def validate_new_password(password: str, email: str = '') -> str:
    password = password or ''
    if len(password) < MIN_PASSWORD_LENGTH:
        raise SecurityError(f'Use at least {MIN_PASSWORD_LENGTH} characters.')
    if password.strip() != password:
        raise SecurityError('The password cannot start or end with a space.')
    kinds = sum([any(c.islower() for c in password), any(c.isupper() for c in password),
                 any(c.isdigit() for c in password), any(not c.isalnum() for c in password)])
    if kinds < 3:
        raise SecurityError('Mix at least three of: lowercase, uppercase, numbers, symbols.')
    shared = (getattr(settings, 'ADMIN_PANEL_PASSWORD', '') or '').strip()
    if shared and hmac.compare_digest(password.encode(), shared.encode()):
        raise SecurityError("Choose a new password, not the old shared one.")
    if email and email.split('@')[0].lower() in password.lower() and len(email.split('@')[0]) >= 4:
        raise SecurityError("Don't put your email name in the password.")
    return password


def hash_password(password: str) -> str:
    return make_password(password)


def password_ok(password: str, encoded: str) -> bool:
    return bool(password and encoded) and check_password(password, encoded)


# ─── Lockouts (Django cache) ────────────────────────────────────────────────

def _key(scope: str, ident: str) -> str:
    return 'admsec:' + scope + ':' + hashlib.sha256(ident.encode('utf-8')).hexdigest()[:32]


def locked_for(scope: str, ident: str) -> int:
    """Seconds left on a lock, or 0."""
    until = cache.get(_key(scope, ident) + ':until') or 0
    left = int(until - time.time())
    return left if left > 0 else 0


def check_not_locked(scope: str, ident: str):
    left = locked_for(scope, ident)
    if left:
        mins = max(1, -(-left // 60))
        raise SecurityError(f'Too many wrong tries. Try again in {mins} minute{"s" if mins != 1 else ""}.')


def record_failure(scope: str, ident: str) -> int:
    """Count a wrong try; returns tries left before the lock."""
    k = _key(scope, ident)
    n = (cache.get(k) or 0) + 1
    if n >= MAX_TRIES:
        cache.set(k + ':until', time.time() + LOCK_SECONDS, LOCK_SECONDS)
        cache.delete(k)
        return 0
    cache.set(k, n, LOCK_SECONDS)
    return MAX_TRIES - n


def clear_failures(scope: str, ident: str):
    k = _key(scope, ident)
    cache.delete(k)
    cache.delete(k + ':until')


def client_ip(request) -> str:
    fwd = (request.META.get('HTTP_X_FORWARDED_FOR') or '').split(',')[0].strip()
    return fwd or request.META.get('REMOTE_ADDR', '') or 'unknown'


# ─── Firestore records ──────────────────────────────────────────────────────

def get_account(db, uid: str) -> dict:
    snap = db.collection(ACCOUNTS).document(uid).get()
    return (snap.to_dict() or {}) if snap.exists else {}


def is_set_up(account: dict) -> bool:
    return bool(account.get('passwordHash') and account.get('totpSecretEnc') and account.get('totpEnabled'))


def account_secret(account: dict) -> str:
    try:
        return decrypt(account['totpSecretEnc'])
    except Exception:
        logger.exception('admin 2FA secret could not be decrypted')
        raise SecurityError('This account\'s authenticator needs to be set up again. Ask the owner to reset it.')


def save_setup(db, uid: str, email: str, password: str, secret: str, step: int):
    from firebase_admin import firestore
    db.collection(ACCOUNTS).document(uid).set({
        'email': email,
        'passwordHash': hash_password(password),
        'totpSecretEnc': encrypt(secret),
        'totpEnabled': True,
        'lastTotpStep': step,
        'setupAt': firestore.SERVER_TIMESTAMP,
        'updatedAt': firestore.SERVER_TIMESTAMP,
    }, merge=True)


def mark_code_used(db, uid: str, step: int):
    from firebase_admin import firestore
    db.collection(ACCOUNTS).document(uid).set({
        'lastTotpStep': step,
        'lastLoginAt': firestore.SERVER_TIMESTAMP,
    }, merge=True)


def log_event(db, request, *, email: str, uid: str = '', ok: bool, step: str, reason: str = ''):
    """Best effort, written in the background so sign-in never waits on it."""
    from firebase_admin import firestore
    row = {
        'email': (email or '').lower()[:200],
        'uid': uid or None,
        'ok': bool(ok),
        'step': step,
        'reason': reason[:200],
        'ip': client_ip(request)[:64],
        'userAgent': (request.META.get('HTTP_USER_AGENT') or '')[:300],
        'at': firestore.SERVER_TIMESTAMP,
    }

    def write():
        try:
            db.collection(EVENTS).add(row)
        except Exception:
            logger.exception('admin login event log failed')

    import threading
    threading.Thread(target=write, name='admin-login-log', daemon=True).start()


def recent_events(db, email: str, limit: int = 20) -> list:
    from google.cloud.firestore_v1.base_query import FieldFilter
    try:
        docs = db.collection(EVENTS).where(filter=FieldFilter('email', '==', (email or '').lower())).limit(200).stream()
        rows = [d.to_dict() or {} for d in docs]
    except Exception:
        logger.exception('admin login events read failed')
        return []
    rows.sort(key=lambda r: r.get('at').timestamp() if hasattr(r.get('at'), 'timestamp') else 0, reverse=True)
    return rows[:limit]


# ─── Session ────────────────────────────────────────────────────────────────

def start_admin_session(request, *, uid: str, email: str):
    """Fresh session id (stops session fixation), then mark signed in."""
    request.session.cycle_key()
    now = time.time()
    for k in ('mfa_pending', 'auth_pin_verified', 'admin_login_otp_verified', 'admin_setup_secret'):
        request.session.pop(k, None)
    request.session['admin'] = True
    request.session['user_id'] = uid
    request.session['email'] = email
    request.session['admin_login_at'] = now
    request.session['admin_last_seen'] = now
    request.session.modified = True


def set_pending(request, *, uid: str, email: str, setup: bool):
    request.session['mfa_pending'] = {'uid': uid, 'email': email, 'setup': setup, 'at': time.time()}
    request.session.modified = True


def get_pending(request) -> Optional[dict]:
    p = request.session.get('mfa_pending')
    if not p or time.time() - float(p.get('at') or 0) > PENDING_SECONDS:
        request.session.pop('mfa_pending', None)
        return None
    return p


def session_expired(session, now: Optional[float] = None) -> Optional[str]:
    """Reason text when an admin session is too old or idle, else None.
    Sessions without timestamps (older sign-ins) get them now."""
    if not session.get('admin'):
        return None
    now = time.time() if now is None else now
    login_at = session.get('admin_login_at')
    last = session.get('admin_last_seen')
    if login_at is None or last is None:
        session['admin_login_at'] = login_at or now
        session['admin_last_seen'] = now
        return None
    if now - float(login_at) > MAX_SESSION_SECONDS:
        return 'For security you were signed out after 12 hours. Please sign in again.'
    if now - float(last) > IDLE_SECONDS:
        return 'You were signed out after 30 minutes without activity. Please sign in again.'
    return None
