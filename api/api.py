"""SudoTag mobile API, mounted at /api/v1/ (see sudo_admin/urls.py)."""

from __future__ import annotations

import logging

from django.conf import settings
from ninja import NinjaAPI
from ninja.errors import AuthenticationError, HttpError, ValidationError

from .errors import ApiError
from .routers import documents, otp, vehicle_contact

logger = logging.getLogger(__name__)

api = NinjaAPI(
    title='SudoTag API',
    version='1',
    urls_namespace='api_v1',
    docs_url='docs' if settings.DEBUG else None,
    openapi_url='openapi.json' if settings.DEBUG else None,
)


def _error(request, code: str, message: str, status: int, extra: dict | None = None):
    body = {'code': code, 'message': message}
    if extra:
        body.update(extra)
    return api.create_response(request, {'error': body}, status=status)


@api.exception_handler(ApiError)
def _api_error(request, exc: ApiError):
    return _error(request, exc.code, exc.message, exc.status, exc.extra)


@api.exception_handler(AuthenticationError)
def _auth_error(request, exc):
    return _error(request, 'unauthenticated', 'Please sign in again.', 401)


@api.exception_handler(ValidationError)
def _validation_error(request, exc):
    return _error(request, 'invalid-argument', 'Some details are missing or not valid.', 422,
                  {'fields': exc.errors})


@api.exception_handler(HttpError)
def _http_error(request, exc):
    return _error(request, 'invalid-argument' if exc.status_code < 500 else 'internal', str(exc), exc.status_code)


@api.exception_handler(Exception)
def _unexpected(request, exc):
    logger.exception('API unhandled error on %s', request.path)
    return _error(request, 'internal', 'Something went wrong. Please try again.', 500)


@api.get('/health', auth=None, tags=['meta'])
def health(request):
    """Database reachable (503 if not) and when the worker last checked in."""
    from django.db import connection

    from .worker import worker_status

    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
    except Exception:
        logger.exception('health: database check failed')
        return api.create_response(request, {'ok': False, 'db': 'down'}, status=503)
    try:
        worker = worker_status()
    except Exception:  # tables missing before migrate
        worker = {'state': 'unknown'}
    return {'ok': True, 'db': connection.vendor, 'worker': worker}


api.add_router('/auth', otp.public_router)
api.add_router('/phone', otp.phone_router)
api.add_router('/', vehicle_contact.router)
api.add_router('/', documents.router)
