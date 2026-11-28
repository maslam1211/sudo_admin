"""App version policy and update telemetry.

    GET  /api/v1/app/config/{platform}     public   same fields as Firestore appConfig/{platform}
    POST /api/v1/app/update-events         signed in  (was a direct app_update_events write)
    PUT  /api/v1/me/app-version            signed in  (was a direct users/{uid} write)
"""

from __future__ import annotations

from datetime import datetime

from ninja import Router, Schema

from appconfig import service

from .. import firebase, ratelimit
from ..errors import ApiError
from ..security import firebase_auth

public_router = Router(tags=['app'])
router = Router(tags=['app'], auth=firebase_auth)

EVENTS_PER_UID_HOUR = 60


def _platform(value: str) -> str:
    p = (value or '').strip().lower()
    if p not in service.PLATFORMS:
        raise ApiError('invalid-argument', 'Unknown platform.')
    return p


@public_router.get('/app/config/{platform}')
def app_config(request, platform: str):
    """`{"exists": false}` when nothing is published (the app then clears its policy)."""
    document = service.config_document(_platform(platform))
    if document is None:
        return {'exists': False}
    out = {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in document.items()}
    out['exists'] = True
    return out


class UpdateEventIn(Schema):
    platform: str
    event: str
    version: str
    build: int
    targetBuild: int | None = None
    urgency: str | None = None
    error: str | None = None
    fromBuild: int | None = None


@router.post('/app/update-events', response={201: dict})
def update_event(request, body: UpdateEventIn):
    platform = _platform(body.platform)
    if not body.event.strip() or len(body.event) > 40 or len(body.version) > 40:
        raise ApiError('invalid-argument', 'Invalid event.')
    ratelimit.hit(f'update-event:{request.auth.uid}', limit=EVENTS_PER_UID_HOUR, window_seconds=3600)
    row = service.record_event(uid=request.auth.uid, platform=platform,
                               data=body.model_dump(exclude_none=True))
    return 201, {'id': row.id}


class AppVersionIn(Schema):
    platform: str
    version: str
    build: int


@router.put('/me/app-version')
def report_app_version(request, body: AppVersionIn):
    """Installed version for adoption numbers. Users still live in Firestore
    (their own phase), so the server writes the same fields there."""
    from firebase_admin import firestore

    platform = _platform(body.platform)
    if len(body.version) > 40 or body.build < 0:
        raise ApiError('invalid-argument', 'Invalid version.')
    firebase.firestore_db().collection('users').document(request.auth.uid).set({
        'appPlatform': platform, 'appVersion': body.version, 'appBuild': body.build,
        'appVersionUpdatedAt': firestore.SERVER_TIMESTAMP,
    }, merge=True)
    return {'ok': True}
