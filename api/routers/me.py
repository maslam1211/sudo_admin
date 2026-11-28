"""The signed-in user's own profile, settings, blocks and family members.

    GET    /api/v1/me                       {exists, profile, settings}
    POST   /api/v1/me/profile               {fullName, emailAddress?, contactNumber?}  first save
    PATCH  /api/v1/me/profile               any of: fullName, emailAddress, contactNumber, city, street,
                                            district, displayAddress, formattedAddress, profilePicture,
                                            bloodGroup, defaultEmergencyContact, liveStatus,
                                            liveStatusCustomText, fullProfile
    PATCH  /api/v1/me/settings              any of the 8 user-settings toggles
    POST   /api/v1/me/password-changed
    POST   /api/v1/me/civic-terms           {version}
    GET    /api/v1/me/blocks                POST {userId, name?, picture?}   DELETE /me/blocks/{userId}
    GET    /api/v1/me/family                POST {name, relation, contactNumber}
    PUT    /api/v1/me/family/{id}           DELETE /api/v1/me/family/{id}
"""

from __future__ import annotations

import json

from ninja import Router

from accounts import service

from .. import firebase, ratelimit
from ..errors import ApiError
from ..security import firebase_auth

router = Router(tags=['me'], auth=firebase_auth)

WRITES_PER_UID_HOUR = 120


def _body(request) -> dict:
    try:
        data = json.loads(request.body or b'{}')
    except (TypeError, ValueError):
        raise ApiError('invalid-argument', 'Invalid request.')
    if not isinstance(data, dict):
        raise ApiError('invalid-argument', 'Invalid request.')
    return data


def _write(request) -> str:
    uid = request.auth.uid
    ratelimit.hit(f'me-write:{uid}', limit=WRITES_PER_UID_HOUR, window_seconds=3600)
    return uid


@router.get('/me')
def get_me(request):
    return service.me(request.auth.uid)


@router.post('/me/profile')
def complete_profile(request):
    body = _body(request)
    return service.complete_profile(firebase.firestore_db(), _write(request),
                                    full_name=str(body.get('fullName') or ''),
                                    email=str(body.get('emailAddress') or ''),
                                    phone=str(body.get('contactNumber') or ''))


@router.patch('/me/profile')
def update_profile(request):
    return service.update_profile(firebase.firestore_db(), _write(request), _body(request))


@router.patch('/me/settings')
def update_settings(request):
    return service.update_settings(firebase.firestore_db(), _write(request), _body(request))


@router.post('/me/password-changed')
def password_changed(request):
    return service.password_changed(firebase.firestore_db(), _write(request))


@router.post('/me/civic-terms')
def civic_terms(request):
    return service.accept_civic_terms(firebase.firestore_db(), _write(request),
                                      str(_body(request).get('version') or ''))


@router.get('/me/blocks')
def blocks(request):
    return {'blocked': service.blocked_list(request.auth.uid)}


@router.post('/me/blocks')
def block(request):
    body = _body(request)
    return service.block(firebase.firestore_db(), _write(request), str(body.get('userId') or ''),
                         name=str(body.get('name') or ''), picture=str(body.get('picture') or ''))


@router.delete('/me/blocks/{user_id}')
def unblock(request, user_id: str):
    return service.unblock(firebase.firestore_db(), _write(request), user_id)


@router.get('/me/family')
def family(request):
    return {'members': service.family_list(request.auth.uid)}


@router.post('/me/family', response={201: dict})
def add_family(request):
    return 201, service.add_family(firebase.firestore_db(), _write(request), _body(request))


@router.put('/me/family/{member_id}')
def update_family(request, member_id: str):
    return service.update_family(firebase.firestore_db(), _write(request), member_id, _body(request))


@router.delete('/me/family/{member_id}')
def delete_family(request, member_id: str):
    return service.delete_family(firebase.firestore_db(), _write(request), member_id)
