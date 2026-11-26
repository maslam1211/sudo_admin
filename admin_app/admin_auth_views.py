"""Admin sign-in second step (authenticator code), first-time setup, and the
Account security page. Logic lives in admin_security.py."""

from __future__ import annotations

import logging

from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.csrf import ensure_csrf_cookie

from . import admin_security as sec

logger = logging.getLogger(__name__)


def _db():
    from .views import db
    return db


@ensure_csrf_cookie
def admin_login_2fa(request):
    """Password accepted; ask for the 6-digit code from the authenticator app."""
    pending = sec.get_pending(request)
    if not pending or pending.get('setup'):
        messages.error(request, 'Sign in again.')
        return redirect('admin_login')
    uid, email = pending['uid'], pending['email']

    if request.method == 'POST':
        try:
            sec.check_not_locked('totp', uid)
            db = _db()
            account = sec.get_account(db, uid)
            if not sec.is_set_up(account):
                request.session.pop('mfa_pending', None)
                messages.error(request, 'This account needs to be set up again. Sign in once more.')
                return redirect('admin_login')
            step = sec.verify_totp(sec.account_secret(account), request.POST.get('code'),
                                   last_step=int(account.get('lastTotpStep') or -1))
            if step is None:
                left = sec.record_failure('totp', uid)
                sec.log_event(db, request, email=email, uid=uid, ok=False, step='code', reason='wrong code')
                if not left:
                    request.session.pop('mfa_pending', None)
                    messages.error(request, 'Too many wrong codes. Sign-in is locked for 15 minutes.')
                    return redirect('admin_login')
                raise sec.SecurityError(f'That code is not right. {left} tr{"y" if left == 1 else "ies"} left.')
            sec.clear_failures('totp', uid)
            sec.mark_code_used(db, uid, step)
            sec.log_event(db, request, email=email, uid=uid, ok=True, step='signed in')
            sec.start_admin_session(request, uid=uid, email=email)
            return redirect('dashboard')
        except sec.SecurityError as exc:
            messages.error(request, str(exc))

    return render(request, 'admin_2fa.html', {'email': email})


@ensure_csrf_cookie
def admin_security_setup(request):
    """First sign-in after the upgrade, or after a reset: create a personal
    password and connect an authenticator app, then sign in."""
    pending = sec.get_pending(request)
    if not pending or not pending.get('setup'):
        messages.error(request, 'Sign in first to set up your account.')
        return redirect('admin_login')
    uid, email = pending['uid'], pending['email']

    enc = request.session.get('admin_setup_secret')
    secret = None
    if enc:
        try:
            secret = sec.decrypt(enc)
        except Exception:
            secret = None
    if not secret:
        secret = sec.new_totp_secret()
        request.session['admin_setup_secret'] = sec.encrypt(secret)
        request.session.modified = True

    if request.method == 'POST':
        password = request.POST.get('password') or ''
        again = request.POST.get('password2') or ''
        try:
            sec.check_not_locked('totp', uid)
            sec.validate_new_password(password, email)
            if password != again:
                raise sec.SecurityError("The two passwords don't match.")
            step = sec.verify_totp(secret, request.POST.get('code'))
            if step is None:
                left = sec.record_failure('totp', uid)
                raise sec.SecurityError(
                    'That code is not right. Check the time on your iPhone is automatic and use the newest code.'
                    + (f' {left} tr{"y" if left == 1 else "ies"} left.' if left else ' Locked for 15 minutes.'))
            db = _db()
            sec.save_setup(db, uid, email, password, secret, step)
            sec.clear_failures('totp', uid)
            sec.log_event(db, request, email=email, uid=uid, ok=True, step='signed in', reason='set up password + authenticator')
            sec.start_admin_session(request, uid=uid, email=email)
            messages.success(request, 'Your account is protected. Next time, sign in with your new password and the code from your iPhone.')
            return redirect('dashboard')
        except sec.SecurityError as exc:
            messages.error(request, str(exc))

    uri = sec.otpauth_uri(secret, email)
    return render(request, 'admin_security_setup.html', {
        'email': email,
        'qr': sec.qr_data_uri(uri),
        'secret_grouped': sec.group_secret(secret),
        'otpauth_uri': uri,
        'min_length': sec.MIN_PASSWORD_LENGTH,
    })


def admin_account_security(request):
    """Signed-in admin: sign-in history and change password."""
    if not request.session.get('admin'):
        return redirect('admin_login')
    uid = request.session.get('user_id') or ''
    email = request.session.get('email') or ''
    db = _db()

    if request.method == 'POST' and request.POST.get('action') == 'change_password':
        try:
            sec.check_not_locked('totp', uid)
            account = sec.get_account(db, uid)
            if not sec.is_set_up(account):
                raise sec.SecurityError('Set up your account first (sign out and sign in again).')
            if not sec.password_ok(request.POST.get('current') or '', account.get('passwordHash', '')):
                sec.record_failure('totp', uid)
                raise sec.SecurityError('Your current password is not right.')
            new = request.POST.get('new') or ''
            sec.validate_new_password(new, email)
            if new != (request.POST.get('new2') or ''):
                raise sec.SecurityError("The two new passwords don't match.")
            step = sec.verify_totp(sec.account_secret(account), request.POST.get('code'),
                                   last_step=int(account.get('lastTotpStep') or -1))
            if step is None:
                sec.record_failure('totp', uid)
                raise sec.SecurityError('The authenticator code is not right.')
            from firebase_admin import firestore
            db.collection(sec.ACCOUNTS).document(uid).set({
                'passwordHash': sec.hash_password(new),
                'lastTotpStep': step,
                'passwordChangedAt': firestore.SERVER_TIMESTAMP,
            }, merge=True)
            sec.clear_failures('totp', uid)
            sec.log_event(db, request, email=email, uid=uid, ok=True, step='password changed')
            messages.success(request, 'Password changed.')
            return redirect('admin_account_security')
        except sec.SecurityError as exc:
            messages.error(request, str(exc))

    account = sec.get_account(db, uid) if uid else {}
    return render(request, 'admin_account_security.html', {
        'events': sec.recent_events(db, email),
        'is_set_up': sec.is_set_up(account),
        'min_length': sec.MIN_PASSWORD_LENGTH,
    })
