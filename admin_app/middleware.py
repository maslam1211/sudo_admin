"""
Custom middleware to exempt API endpoints from CSRF checking
"""
from django.utils.deprecation import MiddlewareMixin

# Classic orange suologo on #000 — injected when a template omits favicon_links.html
_FAVICON_V = '20260711'
_FAVICON_HEAD_SNIPPET = (
    f'<link rel="icon" href="/favicon.ico?v={_FAVICON_V}" sizes="any">\n'
    f'<link rel="icon" type="image/png" sizes="32x32" href="/favicon-32x32.png?v={_FAVICON_V}">\n'
    f'<link rel="icon" type="image/png" sizes="96x96" href="/favicon-96x96.png?v={_FAVICON_V}">\n'
    f'<link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png?v={_FAVICON_V}">\n'
    '<meta name="theme-color" content="#000000">\n'
)


class InjectFaviconMiddleware(MiddlewareMixin):
    """Ensure every HTML page has the site favicon set."""

    def process_response(self, request, response):
        content_type = response.get('Content-Type', '')
        if not content_type.startswith('text/html'):
            return response
        if not hasattr(response, 'content'):
            return response
        try:
            html = response.content.decode(response.charset or 'utf-8')
        except (UnicodeDecodeError, AttributeError):
            return response
        if 'rel="icon"' in html or "rel='icon'" in html:
            return response
        if '</head>' not in html:
            return response
        html = html.replace('</head>', _FAVICON_HEAD_SNIPPET + '</head>', 1)
        response.content = html.encode(response.charset or 'utf-8')
        if 'Content-Length' in response:
            del response['Content-Length']
        return response


class DisableCSRFForAPI(MiddlewareMixin):
    """
    Middleware to disable CSRF checking for all /api/ endpoints.
    This ensures API calls work without CSRF token issues.
    """
    
    def process_request(self, request):
        # Exempt all /api/ paths from CSRF checking
        if request.path.startswith('/admin/api/') or request.path.startswith('/api/'):
            setattr(request, '_dont_enforce_csrf_checks', True)
        return None

