from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.csrf import ensure_csrf_cookie

DEFAULT_LANDING_BANNER_AD = {
    'link': 'https://play.google.com/store/apps/details?id=com.sudotag.sudo&hl=en_GB',
    'message': 'Activate your SudoTag and get 1 year free fleet access',
}

PLAY_STORE_URL = 'https://play.google.com/store/apps/details?id=com.sudotag.sudo&hl=en_GB'
APP_STORE_URL = 'https://apps.apple.com/in/app/sudotag/id6761091033'


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


@ensure_csrf_cookie
def index(request):
    approved_feedbacks = []
    try:
        from admin_app.feedback_service import list_approved_feedbacks
        approved_feedbacks = list_approved_feedbacks(limit=40)
        for item in approved_feedbacks:
            item.pop('_created_raw', None)
    except Exception:
        approved_feedbacks = []

    return render(request, 'index.html', {
        'banner_ads': _landing_banner_ads(request),
        'public_lookup_url': reverse('public_lookup_vehicle'),
        'approved_feedbacks': approved_feedbacks,
        'submit_feedback_url': reverse('submit_feedback'),
        'approved_feedbacks_api_url': reverse('approved_feedbacks_api'),
    })


def terms(request):
    return render(request, 'terms.html')

def privacy(request):
    return render(request, 'privacy.html')

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
