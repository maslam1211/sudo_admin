"""
Email OTP for the web QR-activation flow (activate-id).

The customer proves they own an email address before the activation page tells
them anything about the account behind it, and before a vehicle is linked to it.

- 6-digit codes, stored only as an HMAC keyed with SECRET_KEY.
- Codes expire after OTP_TTL and are single-use.
- At most MAX_VERIFY_ATTEMPTS guesses per code; then a new code is required.
- Sends are rate limited per email (cooldown + hourly cap) and per client IP.
- A successful verify is bound to the browser session *and* the QR id, and
  expires after VERIFIED_TTL.
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import logging
import secrets

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import F
from django.template.loader import render_to_string
from django.utils import timezone

from .models import ActivationEmailOtp

logger = logging.getLogger(__name__)

OTP_LENGTH = 6
OTP_TTL = datetime.timedelta(minutes=10)
RESEND_COOLDOWN_SECONDS = 60
MAX_SENDS_PER_EMAIL_PER_HOUR = 5
MAX_SENDS_PER_IP_PER_HOUR = 20
MAX_VERIFY_ATTEMPTS = 5
VERIFIED_TTL = datetime.timedelta(minutes=30)

SESSION_KEY = 'activate_email_verified'


class EmailOtpError(Exception):
    """A send or verify was refused; str(exc) is safe to show the customer."""

    def __init__(self, message, retry_after=None):
        super().__init__(message)
        self.retry_after = retry_after


def normalize_email(raw):
    return str(raw or '').strip().lower()


def mask_email(email):
    """cu******@gmail.com — enough for the owner to recognise, not to harvest."""
    local, sep, domain = str(email or '').partition('@')
    if not sep:
        return ''
    if len(local) <= 2:
        shown = local[:1]
    else:
        shown = local[:2]
    return f'{shown}{"*" * max(len(local) - len(shown), 3)}@{domain}'


def _code_hash(email, qr_id, code):
    msg = f'{normalize_email(email)}|{qr_id}|{code}'.encode()
    return hmac.new(settings.SECRET_KEY.encode(), msg, hashlib.sha256).hexdigest()


def client_ip(request):
    forwarded = (request.META.get('HTTP_X_FORWARDED_FOR') or '').split(',')[0].strip()
    return forwarded or request.META.get('REMOTE_ADDR') or None


def dummy_code():
    """
    Fixed test code for local development, or '' when disabled.
    Needs BOTH settings.DEBUG and ACTIVATION_DUMMY_EMAIL_OTP (6 digits, e.g. in
    a local .env), so a production server never accepts it by accident.
    """
    code = str(getattr(settings, 'ACTIVATION_DUMMY_EMAIL_OTP', '') or '').strip()
    if settings.DEBUG and len(code) == OTP_LENGTH and code.isdigit():
        return code
    return ''


def issue_code(email, qr_id, ip_address=None, fixed_code=None):
    """
    Create a fresh code for (email, qr_id), retiring any earlier unused one.
    Returns the plain code. Raises EmailOtpError when rate limited.
    `fixed_code` (dummy test mode only) skips rate limits and uses that code.
    """
    email = normalize_email(email)
    now = timezone.now()
    hour_ago = now - datetime.timedelta(hours=1)

    if fixed_code:
        return _store_code(email, qr_id, ip_address, fixed_code, now)

    recent = ActivationEmailOtp.objects.filter(email=email, created_at__gte=hour_ago)
    last = recent.order_by('-created_at').first()
    if last is not None:
        wait = RESEND_COOLDOWN_SECONDS - int((now - last.created_at).total_seconds())
        if wait > 0:
            raise EmailOtpError(
                f'Please wait {wait} seconds before requesting another code.',
                retry_after=wait,
            )
    if recent.count() >= MAX_SENDS_PER_EMAIL_PER_HOUR:
        raise EmailOtpError(
            'Too many codes requested for this email. Please try again in an hour.',
            retry_after=3600,
        )
    if ip_address and ActivationEmailOtp.objects.filter(
        ip_address=ip_address, created_at__gte=hour_ago,
    ).count() >= MAX_SENDS_PER_IP_PER_HOUR:
        raise EmailOtpError(
            'Too many verification requests. Please try again later.',
            retry_after=3600,
        )

    code = ''.join(secrets.choice('0123456789') for _ in range(OTP_LENGTH))
    return _store_code(email, qr_id, ip_address, code, now)


def _store_code(email, qr_id, ip_address, code, now):
    with transaction.atomic():
        ActivationEmailOtp.objects.filter(
            email=email, qr_id=qr_id, consumed=False,
        ).update(consumed=True)
        ActivationEmailOtp.objects.create(
            email=email,
            qr_id=qr_id,
            code_hash=_code_hash(email, qr_id, code),
            ip_address=ip_address,
            expires_at=now + OTP_TTL,
        )
    return code


def discard_latest_code(email, qr_id):
    """
    Drop the code whose email could not be delivered, so it neither works nor
    counts against the customer's cooldown when they fix the address and retry.
    """
    ActivationEmailOtp.objects.filter(
        email=normalize_email(email), qr_id=qr_id, consumed=False,
    ).delete()


def check_code(email, qr_id, code):
    """Consume the live code for (email, qr_id) if `code` matches; else raise EmailOtpError."""
    email = normalize_email(email)
    code = ''.join(c for c in str(code or '') if c.isdigit())
    if len(code) != OTP_LENGTH:
        raise EmailOtpError(f'Enter the {OTP_LENGTH}-digit code from your email.')

    # Failures are raised only after the block commits, so the attempt counter
    # and consumed flag persist (raising inside atomic() would roll them back).
    error = None
    with transaction.atomic():
        otp = (
            ActivationEmailOtp.objects.select_for_update()
            .filter(email=email, qr_id=qr_id, consumed=False)
            .order_by('-created_at')
            .first()
        )
        if otp is None:
            error = 'This code is no longer valid. Request a new code.'
        elif otp.expires_at <= timezone.now():
            ActivationEmailOtp.objects.filter(pk=otp.pk).update(consumed=True)
            error = 'This code has expired. Request a new code.'
        elif otp.attempts >= MAX_VERIFY_ATTEMPTS:
            ActivationEmailOtp.objects.filter(pk=otp.pk).update(consumed=True)
            error = 'Too many incorrect attempts. Request a new code.'
        elif not hmac.compare_digest(otp.code_hash, _code_hash(email, qr_id, code)):
            left = MAX_VERIFY_ATTEMPTS - otp.attempts - 1
            ActivationEmailOtp.objects.filter(pk=otp.pk).update(
                attempts=F('attempts') + 1, consumed=left <= 0,
            )
            if left <= 0:
                error = 'Too many incorrect attempts. Request a new code.'
            else:
                error = f'Incorrect code. {left} attempt{"s" if left != 1 else ""} left.'
        else:
            ActivationEmailOtp.objects.filter(pk=otp.pk).update(consumed=True)
    if error:
        raise EmailOtpError(error)


def send_code_email(email, code):
    """Deliver the code. Raises on SMTP failure so the caller can report it."""
    minutes = int(OTP_TTL.total_seconds() // 60)
    context = {'code': code, 'minutes': minutes, 'support_email': 'support@sudo.com'}
    send_mail(
        subject=f'{code} is your SudoTag verification code',
        message=(
            f'Your SudoTag verification code is {code}.\n\n'
            f'It expires in {minutes} minutes. If you did not try to activate a '
            f'SudoTag QR code, you can ignore this email.\n\nThe SudoTag Team'
        ),
        html_message=render_to_string('activation_otp_email.html', context),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[email],
        fail_silently=False,
    )


# --- Session binding ------------------------------------------------------

def mark_verified(request, qr_id, email, email_as_typed=''):
    verified = dict(request.session.get(SESSION_KEY) or {})
    verified[str(qr_id)] = {
        'email': normalize_email(email),
        'typed': str(email_as_typed or '').strip(),
        'at': timezone.now().timestamp(),
    }
    request.session[SESSION_KEY] = verified
    request.session.modified = True


def verified_email(request, qr_id):
    """(email, email_as_typed) verified in this session for qr_id, or (None, None)."""
    entry = (request.session.get(SESSION_KEY) or {}).get(str(qr_id))
    if not isinstance(entry, dict) or not entry.get('email'):
        return None, None
    age = timezone.now().timestamp() - float(entry.get('at') or 0)
    if age > VERIFIED_TTL.total_seconds():
        clear_verified(request, qr_id)
        return None, None
    return entry['email'], entry.get('typed') or entry['email']


def clear_verified(request, qr_id):
    verified = dict(request.session.get(SESSION_KEY) or {})
    if verified.pop(str(qr_id), None) is not None:
        request.session[SESSION_KEY] = verified
        request.session.modified = True
