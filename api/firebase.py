"""Firebase Admin handles for the API (Auth, Firestore, App Check).

Kept separate from admin_app.views so importing the API does not load the
9,000-line admin views module.
"""

from __future__ import annotations

from functools import lru_cache

from admin_app.firebase_init import ensure_firebase_app


@lru_cache(maxsize=1)
def firestore_db():
    from firebase_admin import firestore

    ensure_firebase_app()
    return firestore.client()


def verify_id_token(token: str) -> dict:
    from firebase_admin import auth

    return auth.verify_id_token(token, app=ensure_firebase_app())


def verify_app_check_token(token: str) -> dict:
    from firebase_admin import app_check

    return app_check.verify_token(token, app=ensure_firebase_app())


def auth_module():
    from firebase_admin import auth

    ensure_firebase_app()
    return auth
