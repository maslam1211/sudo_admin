"""
Admin HTTP views for the Referral Management module.

Read / analytics / export only — referral writes stay in Cloud Functions.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

import pytz
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET

from . import referral_service as svc

logger = logging.getLogger(__name__)

PAGE_SIZES = (20, 50)
_MIN_DT = datetime.min.replace(tzinfo=pytz.UTC)


def _require_admin(request):
    if not request.session.get('admin'):
        messages.error(request, 'Admin access required')
        return redirect('admin_login')
    return None


def _table_filters(request):
    search = (request.GET.get('search') or '').strip()
    status = (request.GET.get('status') or '').strip().lower()
    reward_status = (request.GET.get('reward_status') or '').strip().lower()
    start_date = svc.parse_date_param(request.GET.get('start_date'))
    end_date = svc.parse_date_param(request.GET.get('end_date'))
    sort = (request.GET.get('sort') or 'registeredAt').strip()
    order = (request.GET.get('order') or 'desc').strip().lower()
    try:
        page_size = int(request.GET.get('page_size') or 20)
    except (TypeError, ValueError):
        page_size = 20
    if page_size not in PAGE_SIZES:
        page_size = 20
    return {
        'search': search,
        'status': status if status in svc.REFERRAL_STATUS.values() else '',
        'reward_status': reward_status if reward_status in svc.REWARD_STATUS.values() else '',
        'start_date': start_date,
        'end_date': end_date,
        'start_date_str': request.GET.get('start_date') or '',
        'end_date_str': request.GET.get('end_date') or '',
        'sort': sort,
        'order': order if order in ('asc', 'desc') else 'desc',
        'page_size': page_size,
    }


def _sort_referrals(rows, sort_key: str, order: str):
    reverse = order != 'asc'
    key_fns = {
        'referrerName': lambda r: (r.get('referrerName') or '').lower(),
        'referredUserName': lambda r: (r.get('referredUserName') or '').lower(),
        'referralCode': lambda r: (r.get('referralCode') or '').lower(),
        'status': lambda r: (r.get('status') or '').lower(),
        'rewardStatus': lambda r: (r.get('rewardStatus') or '').lower(),
        'registeredAt': lambda r: r.get('registeredAt') or _MIN_DT,
    }
    key_fn = key_fns.get(sort_key, key_fns['registeredAt'])
    return sorted(rows, key=key_fn, reverse=reverse)


@require_GET
def manage_referrals(request):
    """Overview dashboard: KPIs, charts, top referrers, recent referrals."""
    gate = _require_admin(request)
    if gate:
        return gate

    try:
        overview = svc.build_overview(analytics_days=30)
    except Exception as exc:
        logger.exception('Referral overview failed: %s', exc)
        messages.error(request, f'Failed to load referral overview: {exc}')
        overview = {
            'kpis': svc.compute_kpis([]),
            'series': svc.build_time_series([], days=30),
            'top_referrers': [],
            'recent_referrals': [],
            'truncated': False,
            'fetch_limit': svc.DEFAULT_FETCH_LIMIT,
            'conversion_note': '',
        }

    context = {
        'kpis': overview['kpis'],
        'series': overview['series'],
        'series_json': json.dumps(overview['series']),
        'top_referrers': overview['top_referrers'],
        'recent_referrals': overview['recent_referrals'],
        'truncated': overview['truncated'],
        'fetch_limit': overview['fetch_limit'],
        'conversion_note': overview['conversion_note'],
        'status_pending': svc.REFERRAL_STATUS['PENDING'],
        'status_successful': svc.REFERRAL_STATUS['SUCCESSFUL'],
        'status_rewarded': svc.REFERRAL_STATUS['REWARDED'],
    }
    return render(request, 'manage_referrals.html', context)


@require_GET
def referrals_table(request):
    """Searchable / filterable / paginated referral table."""
    gate = _require_admin(request)
    if gate:
        return gate

    filters = _table_filters(request)
    try:
        rows = svc.fetch_referrals(
            status=filters['status'] or None,
            reward_status=filters['reward_status'] or None,
            start_date=filters['start_date'],
            end_date=filters['end_date'],
            search=filters['search'] or None,
            limit=svc.DEFAULT_FETCH_LIMIT,
        )
        rows = _sort_referrals(rows, filters['sort'], filters['order'])
    except Exception as exc:
        logger.exception('Referral table query failed: %s', exc)
        messages.error(request, f'Failed to load referrals: {exc}')
        rows = []

    paginator = Paginator(rows, filters['page_size'])
    page_number = request.GET.get('page') or 1
    page_obj = paginator.get_page(page_number)

    query_params = request.GET.copy()
    if 'page' in query_params:
        del query_params['page']
    # Sort links rebuild sort/order — keep a base without those keys
    sort_params = query_params.copy()
    for key in ('sort', 'order'):
        if key in sort_params:
            del sort_params[key]

    context = {
        'page_obj': page_obj,
        'paginator': paginator,
        'total_filtered': paginator.count,
        'filters': filters,
        'query_string': query_params.urlencode(),
        'sort_query_string': sort_params.urlencode(),
        'page_sizes': PAGE_SIZES,
        'truncated': len(rows) >= svc.DEFAULT_FETCH_LIMIT,
        'fetch_limit': svc.DEFAULT_FETCH_LIMIT,
        'status_choices': list(svc.REFERRAL_STATUS.values()),
        'reward_status_choices': list(svc.REWARD_STATUS.values()),
    }
    return render(request, 'referrals_table.html', context)


@require_GET
def export_referrals_csv(request):
    gate = _require_admin(request)
    if gate:
        return gate

    filters = _table_filters(request)
    rows = svc.fetch_referrals(
        status=filters['status'] or None,
        reward_status=filters['reward_status'] or None,
        start_date=filters['start_date'],
        end_date=filters['end_date'],
        search=filters['search'] or None,
        limit=svc.EXPORT_ROW_CAP + 1,
    )
    rows = _sort_referrals(rows, filters['sort'], filters['order'])
    csv_text, filename, truncated = svc.export_referrals_csv(rows)

    if truncated:
        messages.warning(
            request,
            f'Export truncated to {svc.EXPORT_ROW_CAP} rows. Narrow filters for a complete set.',
        )

    response = HttpResponse(csv_text, content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    if truncated:
        response['X-Export-Truncated'] = '1'
    return response


@require_GET
def referral_detail(request, referral_id):
    """Single referral edge + links to referrer / referred profiles."""
    gate = _require_admin(request)
    if gate:
        return gate

    referral = svc.get_referral_by_id(referral_id)
    if not referral:
        messages.error(request, 'Referral not found')
        return redirect('referrals_table')

    referrer = svc.get_user_referral_profile(referral.get('referrerUserId') or '')
    referred = svc.get_user_referral_profile(referral.get('referredUserId') or '')

    return render(request, 'referral_detail.html', {
        'referral': referral,
        'referrer': referrer,
        'referred': referred,
    })


@require_GET
def referrer_history(request, user_id):
    """All referrals for one referrer + live users.referralStats."""
    gate = _require_admin(request)
    if gate:
        return gate

    profile = svc.get_user_referral_profile(user_id)
    if not profile:
        messages.error(request, 'User not found')
        return redirect('manage_referrals')

    rows = svc.fetch_referrals(referrer_user_id=user_id, limit=svc.DEFAULT_FETCH_LIMIT)
    kpis = svc.compute_kpis(rows)

    paginator = Paginator(rows, 20)
    page_obj = paginator.get_page(request.GET.get('page') or 1)

    return render(request, 'referrer_history.html', {
        'profile': profile,
        'page_obj': page_obj,
        'paginator': paginator,
        'kpis': kpis,
        'edge_count': len(rows),
    })
