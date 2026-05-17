"""Shared template context (favicon URLs on every page)."""

from django.urls import reverse


def favicon_urls(request):
    """Root-level favicon URLs — work for landing, admin panel, and QR flow."""

    def absolute(view_name):
        path = reverse(view_name)
        if request:
            return request.build_absolute_uri(path)
        from django.conf import settings
        base = getattr(settings, 'BASE_DOMAIN', 'https://sudotag.com').rstrip('/')
        return base + path

    return {
        'favicon_ico_url': absolute('site_favicon'),
        'favicon_32_url': absolute('site_favicon_32'),
        'favicon_96_url': absolute('site_favicon_96'),
        'favicon_apple_url': absolute('site_apple_touch_icon'),
    }
