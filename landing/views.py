from django.shortcuts import render
from django.urls import reverse

DEFAULT_LANDING_BANNER_AD = {
    'link': 'https://play.google.com/store/apps/details?id=com.sudotag.sudo&hl=en_GB',
    'message': 'Activate your SudoTag and get 1 year free fleet access',
}


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


def index(request):
    return render(request, 'index.html', {
        'banner_ads': _landing_banner_ads(request),
    })


def terms(request):
    return render(request, 'terms.html')

def privacy(request):
    return render(request, 'privacy.html')

def how_it_works(request):
    return render(request, 'how_it_works.html')
