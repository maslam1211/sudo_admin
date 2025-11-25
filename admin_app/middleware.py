"""
Custom middleware to exempt API endpoints from CSRF checking
"""
from django.utils.deprecation import MiddlewareMixin


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

