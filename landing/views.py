import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.csrf import ensure_csrf_cookie

logger = logging.getLogger(__name__)
LANDING_DATA_TIMEOUT_SECONDS = 3

# Shown on the temporary site-unavailable notice. Update when restoring the full landing.
SITE_ERROR_AT = datetime(2026, 11, 6, 16, 47, 1, tzinfo=timezone.utc)
DOMAIN_NAME = 'sudotag.com'
DOMAIN_ERROR_CODE = 'ERR_UNDER_MAINTENANCE'

DEFAULT_LANDING_BANNER_AD = {
    'link': 'https://play.google.com/store/apps/details?id=com.sudotag.sudo&hl=en_GB',
    'message': 'Activate your SudoTag and get 1 year free fleet access',
}

PLAY_STORE_URL = 'https://play.google.com/store/apps/details?id=com.sudotag.sudo&hl=en_GB'
APP_STORE_URL = 'https://apps.apple.com/in/app/sudotag/id6761091033'


def _safe_call(fn, default, timeout=LANDING_DATA_TIMEOUT_SECONDS):
    """Run a landing data lookup without letting a hang or error take down the page."""
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        return pool.submit(fn).result(timeout=timeout)
    except Exception:
        logger.exception('SudoTag landing data lookup failed')
        return default
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def _landing_banner_ads(request):
    default = {
        **DEFAULT_LANDING_BANNER_AD,
        'image_url': request.build_absolute_uri(reverse('landing_fleet_promo_png')),
    }
    try:
        from admin_app.views import get_active_banner_ads_for_landing
        return [default, *get_active_banner_ads_for_landing()]
    except Exception:
        return [default]


def _qr_data_uri(payload: str) -> str:
    from admin_app.referral_service import qr_png_data_uri
    try:
        return qr_png_data_uri(payload)
    except Exception:
        return ''


def _domain_expired_context():
    now = datetime.now(timezone.utc)
    occurred_at = SITE_ERROR_AT
    delta = now - occurred_at
    days = max(delta.days, 0)
    return {
        'domain_name': DOMAIN_NAME,
        'domain_error_code': DOMAIN_ERROR_CODE,
        'domain_error_at': occurred_at,
        'domain_error_at_display': occurred_at.strftime('%d %b %Y, %H:%M UTC'),
        'domain_error_days_ago': days,
        'domain_status': 'maintenance',
    }


def render_site_error(request, status=500):
    """Styled technical-error page for landing failures."""
    return render(
        request,
        'domain_expired.html',
        _domain_expired_context(),
        status=status,
    )


def _approved_feedbacks():
    from admin_app.feedback_service import list_approved_feedbacks
    items = list_approved_feedbacks(limit=40)
    for item in items:
        item.pop('_created_raw', None)
    return items


@ensure_csrf_cookie
def index(request):
    """SudoTag landing. Any crash shows the technical error page."""
    try:
        return index_full_landing(request)
    except Exception:
        logger.exception('SudoTag landing failed')
        return render_site_error(request)


@ensure_csrf_cookie
def index_full_landing(request):
    """Full marketing homepage (use after domain renewal)."""
    approved_feedbacks = _safe_call(_approved_feedbacks, [])
    return render(request, 'index.html', {
        'banner_ads': _safe_call(lambda: _landing_banner_ads(request), []),
        'public_lookup_url': reverse('public_lookup_vehicle'),
        'approved_feedbacks': approved_feedbacks,
        'submit_feedback_url': reverse('submit_feedback'),
        'approved_feedbacks_api_url': reverse('approved_feedbacks_api'),
    })


def terms(request):
    return render(request, 'terms.html')

def privacy(request):
    return render(request, 'privacy.html')


def domain_expired(request):
    """Public notice when sudotag.com domain registration has lapsed."""
    return render(request, 'domain_expired.html', _domain_expired_context())


def server_error(request):
    """Uncaught server errors on the public site use the same error page."""
    try:
        path = getattr(request, 'path', '') or ''
        if path.startswith('/admin') or path.startswith('/django-admin'):
            return render(request, 'error.html', status=500)
        return render_site_error(request)
    except Exception:
        from django.http import HttpResponse
        return HttpResponse('Technical error', status=500, content_type='text/plain')


def how_it_works(request):
    # Demo QR for the mobile scan mock — opens the public site when scanned.
    demo_url = request.build_absolute_uri('/')
    return render(request, 'how_it_works.html', {
        'scan_demo_qr_uri': _qr_data_uri(demo_url),
        'scan_demo_qr_url': demo_url,
    })


def referral_invite(request, code):
    """
    Public deep-link landing for https://sudotag.com/r/{CODE}.

    Does not apply the referral — that happens in the mobile app via
    applyReferralCode. This page only resolves the code for display and
    points the visitor to the App / Play Store.
    """
    from admin_app.referral_service import lookup_referral_code, normalize_referral_code

    normalized = normalize_referral_code(code)
    code_info = None
    try:
        code_info = lookup_referral_code(normalized) if normalized else None
    except Exception:
        code_info = None

    is_valid = bool(code_info and code_info.get('isActive') is not False)
    return render(request, 'referral_invite.html', {
        'code': normalized,
        'code_info': code_info,
        'is_valid': is_valid,
        'play_store_url': PLAY_STORE_URL,
        'app_store_url': APP_STORE_URL,
        'referrer_name': (code_info or {}).get('userName') or '',
    })
