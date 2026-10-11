from datetime import timezone

from django.contrib import messages
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods
from firebase_admin import firestore

from . import fleet_service as svc


def _require_admin(request):
    if not request.session.get('admin'):
        messages.error(request, 'Admin access required')
        return redirect('admin_login')
    return None


def _db():
    return firestore.client()


def _filtered_fleets(fleets, status, search):
    if status == 'active':
        fleets = [f for f in fleets if f.get('isActive')]
    elif status == 'scheduled':
        fleets = [f for f in fleets if f.get('isScheduled')]
    elif status == 'inactive':
        fleets = [f for f in fleets if not f.get('isActive') and not f.get('isScheduled')]
    if search:
        fleets = [
            f for f in fleets
            if search in str(f.get('name') or '').lower()
            or search in str(f.get('ownerId') or '').lower()
            or search in str(f.get('gstin') or '').lower()
            or search in str(f.get('city') or '').lower()
        ]
    return fleets


@require_http_methods(['GET'])
def manage_fleets(request):
    gate = _require_admin(request)
    if gate:
        return gate
    try:
        fleets = svc.list_fleets(_db())
    except Exception as e:
        messages.error(request, f'Error loading fleets: {e}')
        fleets = []

    active_count = sum(1 for f in fleets if f.get('isActive'))
    scheduled_count = sum(1 for f in fleets if f.get('isScheduled'))
    status = (request.GET.get('status') or '').strip().lower()
    search_raw = request.GET.get('search') or ''
    fleets = _filtered_fleets(fleets, status, search_raw.strip().lower())

    page = request.GET.get('page', 1)
    paginator = Paginator(fleets, 20)
    try:
        page_obj = paginator.page(page)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    return render(request, 'manage_fleets.html', {
        'fleets': page_obj,
        'paginator': paginator,
        'status': status,
        'search': search_raw,
        'active_count': active_count,
        'scheduled_count': scheduled_count,
    })


@require_http_methods(['GET'])
def export_fleets_csv(request):
    gate = _require_admin(request)
    if gate:
        return gate
    try:
        fleets = svc.list_fleets(_db())
    except Exception as e:
        messages.error(request, f'Error loading fleets: {e}')
        return redirect('manage_fleets')
    status = (request.GET.get('status') or '').strip().lower()
    search = (request.GET.get('search') or '').strip().lower()
    fleets = _filtered_fleets(fleets, status, search)
    response = HttpResponse(svc.fleets_to_csv(fleets), content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="sudotag-fleets.csv"'
    return response


@require_http_methods(['GET', 'POST'])
def manage_fleet_detail(request, fleet_id):
    gate = _require_admin(request)
    if gate:
        return gate

    fleet = svc.get_fleet(_db(), fleet_id)
    if not fleet:
        messages.error(request, 'Fleet not found')
        return redirect('manage_fleets')

    if request.method == 'POST':
        action = (request.POST.get('action') or '').strip()
        try:
            if action == 'activate':
                cycle = request.POST.get('billingCycle') or 'monthly'
                window = svc.parse_model_window(
                    request.POST.get('startDate'),
                    request.POST.get('endDate'),
                    billing_cycle=cycle,
                )
                svc.activate_subscription(
                    _db(),
                    fleet_id,
                    plan_id=request.POST.get('planId') or fleet.get('planId') or 'starter',
                    billing_cycle=cycle,
                    starts_at=window['subscriptionStartsAt'],
                    expires_at=window['subscriptionExpiresAt'],
                )
                if window['scheduled']:
                    start = window['subscriptionStartsAt'].strftime('%d %b %Y')
                    end = window['subscriptionExpiresAt'].strftime('%d %b %Y')
                    messages.success(
                        request,
                        f'Model scheduled from {start} until {end}. Shifts in the app open on the start date.',
                    )
                else:
                    messages.success(request, 'Subscription activated. The owner can open Me → SudoTag Fleet in the app.')
            elif action == 'extend':
                days = int(request.POST.get('days') or 0)
                new_end = svc.extend_subscription(_db(), fleet_id, fleet, days)
                messages.success(
                    request,
                    f'End date moved to {new_end.strftime("%d %b %Y")}. The model is unchanged.',
                )
            elif action == 'company':
                svc.update_company(
                    _db(),
                    fleet_id,
                    name=request.POST.get('name') or '',
                    gstin=request.POST.get('gstin') or '',
                    city=request.POST.get('city') or '',
                )
                messages.success(request, 'Company details saved.')
            elif action == 'cancel':
                svc.cancel_subscription(_db(), fleet_id)
                messages.success(request, 'Subscription cancelled.')
            else:
                messages.error(request, 'Unknown action.')
        except Exception as e:
            messages.error(request, f'Update failed: {e}')
        return redirect('manage_fleet_detail', fleet_id=fleet_id)

    drivers = []
    assigned_vehicles = []
    shift_logs = []
    try:
        drivers = svc.list_drivers(_db(), fleet_id)
        driver_ids = {d['id'] for d in drivers if d.get('id')}
        assigned_vehicles = svc.list_assigned_vehicles(_db(), fleet.get('ownerId'), driver_ids)
        shift_logs = svc.list_shift_logs(_db(), fleet_id)
    except Exception as e:
        messages.error(request, f'Could not load drivers: {e}')

    def _date_value(value):
        if not value:
            return ''
        if getattr(value, 'tzinfo', None):
            value = value.astimezone(timezone.utc)
        return value.strftime('%Y-%m-%d')

    return render(request, 'manage_fleet_detail.html', {
        'fleet': fleet,
        'drivers': drivers,
        'assigned_vehicles': assigned_vehicles,
        'shift_logs': shift_logs,
        'plans': svc.FLEET_PLANS,
        'start_date': _date_value(fleet.get('startsAt')),
        'end_date': _date_value(fleet.get('expiresAt')),
        'on_shift_count': sum(1 for v in assigned_vehicles if not v.get('isScheduled')),
        'scheduled_shift_count': sum(1 for v in assigned_vehicles if v.get('isScheduled')),
    })
