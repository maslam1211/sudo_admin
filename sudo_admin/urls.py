"""
URL configuration for sudo_admin project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from pathlib import Path
from django.http import FileResponse, HttpResponse


_FAVICON_DIR = Path(settings.BASE_DIR) / 'admin_app' / 'static' / 'assets' / 'img'


def _favicon_file_response(filename, content_type):
    path = _FAVICON_DIR / filename
    if path.is_file():
        resp = FileResponse(path.open('rb'), content_type=content_type)
        resp['Cache-Control'] = 'public, max-age=86400'
        return resp
    return HttpResponse(status=404)


def favicon_view(request):
    """SudoTag favicon — orange suologo on #000 (landing, admin, QR flow)."""
    resp = _favicon_file_response('favicon.ico', 'image/x-icon')
    return resp if resp.status_code != 404 else HttpResponse(status=204)


def favicon_32_view(request):
    return _favicon_file_response('favicon-32x32.png', 'image/png')


def favicon_96_view(request):
    return _favicon_file_response('favicon-96x96.png', 'image/png')


def apple_touch_icon_view(request):
    return _favicon_file_response('apple-touch-icon.png', 'image/png')


def brand_logo_view(request):
    """Serve SudoTag mark from the app bundle (survives /static/ misconfig or stale collectstatic)."""
    logo = Path(settings.BASE_DIR) / 'admin_app' / 'static' / 'assets' / 'img' / 'sudotag-logo.png'
    if logo.is_file():
        resp = FileResponse(logo.open('rb'), content_type='image/png')
        resp['Cache-Control'] = 'public, max-age=86400'
        return resp
    return HttpResponse(status=404)


def landing_header_logo_view(request):
    """Landing page header logo (logo-cmyk — survives stale collectstatic on sudotag.com)."""
    logo = Path(settings.BASE_DIR) / 'admin_app' / 'static' / 'images' / 'logo-cmyk.png'
    if logo.is_file():
        resp = FileResponse(logo.open('rb'), content_type='image/png')
        resp['Cache-Control'] = 'public, max-age=86400'
        return resp
    return HttpResponse(status=404)


def notify_flow_center_logo_view(request):
    """Notify-flow modal mark (same resilience as brand_logo_png for QR pages on sudotag.com)."""
    logo = Path(settings.BASE_DIR) / 'admin_app' / 'static' / 'images' / 'sudomainlogo.png'
    if logo.is_file():
        resp = FileResponse(logo.open('rb'), content_type='image/png')
        resp['Cache-Control'] = 'public, max-age=86400'
        return resp
    return HttpResponse(status=404)


def notify_sending_wheel_json_view(request):
    """Lottie JSON for notify sending overlay (avoids broken animation when /static/ is misconfigured)."""
    wheel = Path(settings.BASE_DIR) / 'admin_app' / 'static' / 'images' / 'wheel.json'
    if wheel.is_file():
        resp = FileResponse(wheel.open('rb'), content_type='application/json')
        resp['Cache-Control'] = 'public, max-age=86400'
        return resp
    return HttpResponse(status=404)


def sudo_mobile_flow_css_view(request):
    """Mobile QR flow theme — survives broken STATIC_URL / nginx / missing collectstatic."""
    css = Path(settings.BASE_DIR) / 'admin_app' / 'static' / 'assets' / 'css' / 'sudo_mobile_flow.css'
    if css.is_file():
        resp = FileResponse(css.open('rb'), content_type='text/css; charset=utf-8')
        mtime = int(css.stat().st_mtime)
        resp['ETag'] = f'"{mtime}"'
        resp['Cache-Control'] = 'public, max-age=3600, must-revalidate'
        return resp
    return HttpResponse(status=404)


def vehicle_brands_models_json_view(request):
    """Vehicle catalog for activate-id page fetch()."""
    data = Path(settings.BASE_DIR) / 'admin_app' / 'static' / 'assets' / 'data' / 'vehicle_brands_models.json'
    if data.is_file():
        resp = FileResponse(data.open('rb'), content_type='application/json; charset=utf-8')
        resp['Cache-Control'] = 'public, max-age=86400'
        return resp
    return HttpResponse(status=404)


urlpatterns = [
    path('favicon.ico', favicon_view, name='site_favicon'),
    path('favicon-32x32.png', favicon_32_view, name='site_favicon_32'),
    path('favicon-96x96.png', favicon_96_view, name='site_favicon_96'),
    path('apple-touch-icon.png', apple_touch_icon_view, name='site_apple_touch_icon'),
    path('admin/brand-logo.png', brand_logo_view, name='brand_logo_png'),
    path(
        'admin/landing-header-logo.png',
        landing_header_logo_view,
        name='landing_header_logo_png',
    ),
    path(
        'admin/sudomain-logo.png',
        notify_flow_center_logo_view,
        name='notify_flow_center_logo_png',
    ),
    path(
        'admin/notify-sending-wheel.json',
        notify_sending_wheel_json_view,
        name='notify_sending_wheel_json',
    ),
    path(
        'admin/css/sudo-mobile-flow.css',
        sudo_mobile_flow_css_view,
        name='sudo_mobile_flow_css',
    ),
    path(
        'admin/data/vehicle-brands-models.json',
        vehicle_brands_models_json_view,
        name='vehicle_brands_models_json',
    ),
    path('django-admin/', admin.site.urls),
    path('admin/', include('admin_app.urls')),
    path('', include('landing.urls')),  # Landing page at root path
    # No catch-all redirect - invalid paths will show 404 error instead
]

# This handles 404 errors - shows error instead of redirecting
handler404 = 'admin_app.views.custom_404'


if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)