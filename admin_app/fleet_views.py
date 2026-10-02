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
    elif status == 'inactive':
        fleets = [f for f in fleets if not f.get('isActive')]
    if search:
        fleets = [
            f for f in fleets
            if search in str(f.get('name') or '').lower()
            or search in str(f.get('ownerId') or '').lower()
            or search in str(f.get('gstin') or '').lower()
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
                svc.activate_subscription(
                    _db(),
                    fleet_id,
                    plan_id=request.POST.get('planId') or fleet.get('planId') or 'starter',
                    billing_cycle=request.POST.get('billingCycle') or 'monthly',
                )
                messages.success(request, 'Subscription activated. The owner can open Me → SudoTag Fleet in the app.')
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
    try:
        drivers = svc.list_drivers(_db(), fleet_id)
        driver_ids = {d['id'] for d in drivers if d.get('id')}
        assigned_vehicles = svc.list_assigned_vehicles(_db(), fleet.get('ownerId'), driver_ids)
    except Exception as e:
        messages.error(request, f'Could not load drivers: {e}')

    return render(request, 'manage_fleet_detail.html', {
        'fleet': fleet,
        'drivers': drivers,
        'assigned_vehicles': assigned_vehicles,
        'plans': svc.FLEET_PLANS,
    })
