"""One error shape for every API response.

    {"error": {"code": "failed-precondition", "message": "…"}}

Codes reuse the Cloud Functions callable codes the app already maps
(lib/core/app_error_mapper.dart), so moving a call from a callable to this
API does not change how errors read in the app.
"""

from __future__ import annotations

HTTP_STATUS_FOR_CODE = {
    'invalid-argument': 400,
    'failed-precondition': 400,
    'unauthenticated': 401,
    'permission-denied': 403,
    'not-found': 404,
    'already-exists': 409,
    'resource-exhausted': 429,
    'internal': 500,
    'unavailable': 503,
}


class ApiError(Exception):
    def __init__(self, code: str, message: str, *, status: int | None = None, extra: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status or HTTP_STATUS_FOR_CODE.get(code, 400)
        self.extra = extra or {}

    def payload(self) -> dict:
        body = {'code': self.code, 'message': self.message}
        body.update(self.extra)
        return {'error': body}
