"""
App Version Management: admin page, form publish, and the REST API.

    GET  /api/v1/app/version-check            public
    GET  /api/v1/admin/app-versions           admin session
    POST /api/v1/admin/app-versions           admin session + CSRF token
    PUT  /api/v1/admin/app-versions/<id>      admin session + CSRF token (id = android|ios)

/api/ paths skip Django's CSRF middleware (DisableCSRFForAPI), so the admin
endpoints, which authenticate with the session cookie, check the CSRF token
themselves; otherwise any site an admin visits could publish a forced update.
"""
from __future__ import annotations

import json
import logging

from django.contrib import messages
from django.http import JsonResponse
from django.middleware.csrf import CsrfViewMiddleware
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from . import app_version_service as svc

logger = logging.getLogger(__name__)


def _require_admin(request):
    if not request.session.get('admin'):
        messages.error(request, 'Admin access required')
        return redirect('admin_login')
    return None


def _admin_identity(request) -> tuple[str, str]:
    return (request.session.get('email') or '', request.session.get('user_id') or '')


def _api_admin_guard(request, *, write: bool):
    """JSON 401/403 for the admin API; CSRF for writes despite DisableCSRFForAPI."""
    if not request.session.get('admin'):
        return JsonResponse({'error': 'Admin sign-in required.'}, status=401)
    if write:
        # The global CsrfViewMiddleware already "accepted" this request
        # (csrf_processing_done) because of DisableCSRFForAPI; reset both
        # flags or the check below returns early without checking.
        request._dont_enforce_csrf_checks = False
        request.csrf_processing_done = False
        rejection = CsrfViewMiddleware(lambda r: None).process_view(request, None, (), {})
        if rejection is not None:
            return JsonResponse({'error': 'CSRF token missing or invalid.'}, status=403)
    return None


def _json_body(request) -> dict:
    try:
        body = json.loads(request.body or b'{}')
    except (ValueError, UnicodeDecodeError):
        return {}
    return body if isinstance(body, dict) else {}


# ── Admin page ───────────────────────────────────────────────────────────────

@require_GET
def manage_app_versions(request):
    guard = _require_admin(request)
    if guard:
        return guard

    db = svc.get_db()
    platforms = []
    load_error = None
    for platform in svc.PLATFORMS:
        entry = {'platform': platform, 'label': 'Android' if platform == 'android' else 'iOS'}
        try:
            config = svc.get_config(db, platform)
            entry['config'] = svc.admin_config_payload(platform, config)
            entry['releases'] = svc.list_releases(db, platform, limit=15)
            try:
                entry['stats'] = svc.adoption_stats(db, platform, config)
            except Exception:  # missing index right after deploy, quota, etc.
                logger.exception('App version stats failed for %s', platform)
                entry['stats'] = None
        except Exception:
            logger.exception('Loading app version config failed for %s', platform)
            load_error = 'Could not load version settings from Firestore. Try again.'
            entry.setdefault('config', svc.admin_config_payload(platform, None))
            entry.setdefault('releases', [])
            entry.setdefault('stats', None)
        platforms.append(entry)

    try:
        events = svc.recent_events(db, limit=40)
    except Exception:
        logger.exception('Loading app update events failed')
        events = []
    try:
        total_users = svc.total_users(db)
    except Exception:
        total_users = None

    reporting = sum((p['stats'] or {}).get('reporting', 0) for p in platforms)
    return render(request, 'app_versions.html', {
        'platforms': platforms,
        'events': events,
        'load_error': load_error,
        'total_users': total_users,
        'not_reported': (total_users - reporting) if total_users is not None else None,
        'form_errors': request.session.pop('app_version_errors', {}),
        'form_platform': request.session.pop('app_version_error_platform', ''),
    })


@require_POST
def publish_app_version(request, platform):
    guard = _require_admin(request)
    if guard:
        return guard
    try:
        platform = svc.check_platform(platform)
    except svc.UnknownPlatform:
        messages.error(request, 'Unknown platform.')
        return redirect('manage_app_versions')

    data = request.POST.dict()
    # Unchecked checkboxes are absent from the form.
    data['force_update'] = 'force_update' in request.POST
    data['update_enabled'] = 'update_enabled' in request.POST
    clean, errors = svc.validate_config(platform, data)
    if errors:
        request.session['app_version_errors'] = errors
        request.session['app_version_error_platform'] = platform
        messages.error(request, 'Fix the highlighted fields and publish again.')
        return redirect('manage_app_versions')

    email, uid = _admin_identity(request)
    try:
        svc.publish_config(svc.get_db(), platform, clean, admin_email=email, admin_uid=uid)
    except Exception:
        logger.exception('Publishing app version failed for %s', platform)
        messages.error(request, 'Publishing failed. Nothing was changed. Try again.')
        return redirect('manage_app_versions')

    label = 'Android' if platform == 'android' else 'iOS'
    messages.success(
        request,
        f'{label} {clean["latestVersion"]} ({clean["latestBuild"]}) published. '
        'Apps pick it up on their next launch or resume.',
    )
    return redirect('manage_app_versions')


# ── REST API ─────────────────────────────────────────────────────────────────

@require_GET
def api_version_check(request):
    """Public. ?platform=android|ios&build=103&version=1.1.53"""
    try:
        platform = svc.check_platform(request.GET.get('platform', ''))
    except svc.UnknownPlatform:
        return JsonResponse({'error': 'platform must be android or ios.'}, status=400)
    build_raw = (request.GET.get('build') or '').strip()
    if build_raw and not build_raw.isdigit():
        return JsonResponse({'error': 'build must be a whole number.'}, status=400)
    version = (request.GET.get('version') or '').strip()[:40]
    try:
        config = svc.get_config(svc.get_db(), platform)
    except Exception:
        logger.exception('version-check: Firestore read failed')
        return JsonResponse({'error': 'Version service unavailable.'}, status=503)
    payload = svc.version_check_payload(
        platform, config, installed_build=int(build_raw or 0), installed_version=version)
    response = JsonResponse(payload)
    response['Cache-Control'] = 'public, max-age=60'
    return response


@require_http_methods(['GET', 'POST'])
def api_admin_app_versions(request):
    guard = _api_admin_guard(request, write=request.method == 'POST')
    if guard:
        return guard
    db = svc.get_db()
    if request.method == 'GET':
        try:
            items = [svc.admin_config_payload(p, svc.get_config(db, p)) for p in svc.PLATFORMS]
        except Exception:
            logger.exception('admin app-versions list failed')
            return JsonResponse({'error': 'Could not read version settings.'}, status=503)
        return JsonResponse({'results': items})

    body = _json_body(request)
    try:
        platform = svc.check_platform(str(body.get('platform', '')))
    except svc.UnknownPlatform:
        return JsonResponse({'errors': {'platform': 'Must be android or ios.'}}, status=400)
    return _publish_json(request, db, platform, body, created=True)


@require_http_methods(['PUT'])
def api_admin_app_version_detail(request, version_id):
    guard = _api_admin_guard(request, write=True)
    if guard:
        return guard
    try:
        platform = svc.check_platform(version_id)
    except svc.UnknownPlatform:
        return JsonResponse({'error': 'Not found.'}, status=404)
    return _publish_json(request, svc.get_db(), platform, _json_body(request), created=False)


def _publish_json(request, db, platform, body, *, created):
    clean, errors = svc.validate_config(platform, body)
    if errors:
        return JsonResponse({'errors': errors}, status=400)
    email, uid = _admin_identity(request)
    try:
        svc.publish_config(db, platform, clean, admin_email=email, admin_uid=uid)
        stored = svc.get_config(db, platform)
    except Exception:
        logger.exception('admin app-versions publish failed for %s', platform)
        return JsonResponse({'error': 'Publishing failed. Nothing was changed.'}, status=503)
    return JsonResponse(svc.admin_config_payload(platform, stored), status=201 if created else 200)
