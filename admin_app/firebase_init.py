"""Initialise the default Firebase Admin app (project sudotag-faa80) once."""
from __future__ import annotations

import json
import logging
import os

import firebase_admin
from firebase_admin import credentials

logger = logging.getLogger(__name__)


def ensure_firebase_app():
    """Return the default app, creating it from the environment the first time.

    Credentials come from the environment or the project .env on the VPS. Never commit the key.
      FIREBASE_SERVICE_ACCOUNT_JSON  the key file's JSON content, or
      GOOGLE_APPLICATION_CREDENTIALS a path to the key file on the server
    Get a key: Firebase Console > sudotag-faa80 > Project settings >
    Service accounts > Generate new private key.
    """
    if firebase_admin._apps:
        return firebase_admin.get_app()

    sa_json = os.environ.get('FIREBASE_SERVICE_ACCOUNT_JSON', '').strip()
    sa_path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS', '').strip()
    if sa_json:
        cred = credentials.Certificate(json.loads(sa_json))
    elif sa_path:
        cred = credentials.Certificate(sa_path)
    else:
        raise RuntimeError(
            'Firebase credentials missing: set FIREBASE_SERVICE_ACCOUNT_JSON '
            '(or GOOGLE_APPLICATION_CREDENTIALS) to the sudotag-faa80 Admin SDK key.'
        )

    project_id = getattr(cred, 'project_id', '') or ''
    if project_id != 'sudotag-faa80':
        logger.warning('Firebase Admin is using project %r, not sudotag-faa80', project_id)

    # storageBucket used for vehicle photo uploads
    return firebase_admin.initialize_app(cred, {
        'storageBucket': os.environ.get('FIREBASE_STORAGE_BUCKET', 'sudotag-faa80.firebasestorage.app'),
    })
