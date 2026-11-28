"""Request ids and log formatting.

Every request gets an id (from nginx's X-Request-ID, or a new one). It is
returned in the X-Request-ID response header and added to every log line
written while handling the request, so a user's error report can be matched
to the server log.
"""

from __future__ import annotations

import contextvars
import json
import logging
import re
import time
import uuid

_request_id: contextvars.ContextVar[str] = contextvars.ContextVar('request_id', default='-')
_VALID_ID = re.compile(r'^[A-Za-z0-9._-]{8,64}$')

api_logger = logging.getLogger('api.requests')


def current_request_id() -> str:
    return _request_id.get()


class RequestIdFilter(logging.Filter):
    def filter(self, record):
        record.request_id = _request_id.get()
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line (LOG_FORMAT=json)."""

    def format(self, record):
        payload = {
            'ts': self.formatTime(record, '%Y-%m-%dT%H:%M:%S%z'),
            'level': record.levelname,
            'logger': record.name,
            'request_id': getattr(record, 'request_id', '-'),
            'message': record.getMessage(),
        }
        if record.exc_info:
            payload['exc'] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


class RequestIdMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        incoming = request.headers.get('X-Request-ID', '')
        request_id = incoming if _VALID_ID.match(incoming) else uuid.uuid4().hex
        token = _request_id.set(request_id)
        started = time.monotonic()
        try:
            response = self.get_response(request)
        finally:
            _request_id.reset(token)
        response['X-Request-ID'] = request_id
        if request.path.startswith('/api/v1/'):
            # Path and status only: no bodies, tokens or phone numbers.
            api_logger.info(
                'api %s %s -> %s in %dms [%s]', request.method, request.path,
                response.status_code, (time.monotonic() - started) * 1000, request_id,
            )
        return response
