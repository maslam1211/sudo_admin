from django.shortcuts import render

from admin_app.views import get_active_banner_ads_for_landing

DEFAULT_LANDING_BANNER_AD = {
    'image_static': 'landing/img/sudotag-fleet-promo-ad.png',
    'link': 'https://play.google.com/store/apps/details?id=com.sudotag.sudo&hl=en_GB',
    'message': 'Activate your SudoTag and get 1 year free fleet access',
}


def _landing_banner_ads():
    ads = [DEFAULT_LANDING_BANNER_AD]
    ads.extend(get_active_banner_ads_for_landing())
    return ads


def index(request):
    return render(request, 'index.html', {
        'banner_ads': _landing_banner_ads(),
    })


def terms(request):
    return render(request, 'terms.html')

def privacy(request):
    return render(request, 'privacy.html')

def how_it_works(request):
    return render(request, 'how_it_works.html')
