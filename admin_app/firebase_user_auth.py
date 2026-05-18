"""Firebase Auth helpers for web-panel user registration (activate-id flow)."""

from __future__ import annotations

import logging
import secrets
import string
from typing import Tuple

from firebase_admin import auth

logger = logging.getLogger(__name__)


def generate_random_password(length: int = 12) -> str:
    """
    Cryptographically secure password with upper, lower, digit, and special char.
    Matches mobile app expectations better than a short fixed pattern.
    """
    uppercase = string.ascii_uppercase
    lowercase = string.ascii_lowercase
    digits = string.digits
    special = '!@#$%^&*'

    password_chars = [
        secrets.choice(uppercase),
        secrets.choice(lowercase),
        secrets.choice(digits),
        secrets.choice(special),
    ]
    all_chars = uppercase + lowercase + digits + special
    password_chars.extend(secrets.choice(all_chars) for _ in range(length - 4))
    secrets.SystemRandom().shuffle(password_chars)
    return ''.join(password_chars)


def create_or_update_firebase_user(
    email: str,
    full_name: str,
    password: str | None = None,
) -> Tuple[auth.UserRecord, str, bool]:
    """
    Create or update a Firebase Auth user.

    Returns (user_record, password_used, is_new_user).
    Existing users get an updated password so welcome email credentials work.
    """
    if password is None:
        password = generate_random_password(12)

    email = (email or '').strip()
    full_name = (full_name or '').strip()

    try:
        user = auth.get_user_by_email(email)
        user = auth.update_user(
            user.uid,
            password=password,
            display_name=full_name,
            disabled=False,
            email_verified=False,
        )
        logger.info('Updated existing Firebase Auth user %s', user.uid)
        return user, password, False
    except auth.UserNotFoundError:
        pass

    try:
        user = auth.create_user(
            email=email,
            password=password,
            display_name=full_name,
            email_verified=False,
            disabled=False,
        )
        logger.info('Created Firebase Auth user %s', user.uid)
        return user, password, True
    except auth.EmailAlreadyExistsError:
        user = auth.get_user_by_email(email)
        user = auth.update_user(
            user.uid,
            password=password,
            display_name=full_name,
            disabled=False,
            email_verified=False,
        )
        logger.info('Resolved race: updated Firebase Auth user %s', user.uid)
        return user, password, False
