"""Customer detail page and vehicle actions (logic in customer_admin.py)."""

from __future__ import annotations

import logging

from django.contrib import messages
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from . import customer_admin as ca

logger = logging.getLogger(__name__)


def _db():
    from .views import db
    return db


def _auth():
    from firebase_admin import auth
    return auth


def _admin_required(request):
    if not request.session.get('admin'):
        messages.error(request, 'Admin access required')
        return redirect('admin_login')
    return None


def _log(request, what, ref):
    logger.info('admin %s %s %s', request.session.get('email'), what, ref)


def customer_detail(request, user_id):
    deny = _admin_required(request)
    if deny:
        return deny
    from .views import _is_protected_admin_user
    db = _db()
    ref = db.collection('users').document(user_id)

    if request.method == 'POST':
        action = request.POST.get('action')
        try:
            if action == 'save':
                res = ca.update_customer(db, user_id, request.POST, auth_module=_auth())
                if res['changed']:
                    _log(request, 'edited customer', user_id)
                    extra = f" Updated on {res['vehicles_updated']} vehicle{'s' if res['vehicles_updated'] != 1 else ''} too." if res['vehicles_updated'] else ''
                    messages.success(request, 'Customer saved.' + extra)
                else:
                    messages.info(request, 'Nothing changed.')
                return redirect('customer_detail', user_id=user_id)
            if action == 'delete':
                data = (ref.get().to_dict() or {})
                expected = str(data.get('emailAddress') or 'DELETE').strip().lower()
                if (request.POST.get('confirm') or '').strip().lower() not in (expected, 'delete'):
                    raise ca.CustomerAdminError("Type the customer's email (or DELETE) to confirm.")
                res = ca.delete_customer(db, user_id, auth_module=_auth(), is_protected=_is_protected_admin_user)
                _log(request, 'deleted customer', user_id)
                messages.success(request, (
                    f"Customer deleted and archived: {res['vehicles']} vehicle(s) archived, "
                    f"{res['qrs_freed']} QR sticker(s) and {res['smart_tags_freed']} Smart Tag(s) freed"
                    + (', sign-in account removed.' if res['auth_deleted'] else '.')))
                return redirect('manage_users')
            raise ca.CustomerAdminError('Unknown action.')
        except ca.CustomerAdminError as exc:
            messages.error(request, str(exc))
        except Exception:
            logger.exception('customer_detail %s failed for %s', action, user_id)
            messages.error(request, 'Something went wrong. Nothing more was changed; try again.')

    snap = ref.get()
    if not snap.exists:
        messages.error(request, 'Customer not found.')
        return redirect('manage_users')
    user = snap.to_dict() or {}
    vehicles = [{'id': v.id, **(v.to_dict() or {})} for v in ca.vehicles_of(db, user_id)]
    vehicles.sort(key=lambda v: str(v.get('registrationNumber') or ''))
    qrs = [{'id': q.id, **(q.to_dict() or {})} for q in ca.qrs_of(db, user_id)]
    tags = [{'id': t.id, **(t.to_dict() or {})} for t in ca.smart_tags_of(db, user_id)]
    try:
        orders = [{'id': o.id, 'orderStatus': 0, **(o.to_dict() or {})} for o in ca.orders_of(db, user_id)]
        orders.sort(key=lambda o: str(o.get('timestamp') or ''), reverse=True)
    except Exception:
        orders = []
    from .views import STATUS_MAPPING
    return render(request, 'customer_detail.html', {
        'uid': user_id,
        'user': user,
        'vehicles': vehicles,
        'duplicates': ca.duplicate_registrations(vehicles),
        'qrs': qrs,
        'tags': tags,
        'orders': orders[:10],
        'orders_count': len(orders),
        'blood_groups': ca.BLOOD_GROUPS,
        'protected': _is_protected_admin_user(user),
        'STATUS_MAPPING': STATUS_MAPPING,
    })


@require_POST
def vehicle_admin_action(request, vehicle_id):
    deny = _admin_required(request)
    if deny:
        return deny
    db = _db()
    action = request.POST.get('action')
    back = reverse('manage_vehicle_detail', args=[vehicle_id])
    try:
        if action == 'save':
            changed = ca.update_vehicle(db, vehicle_id, request.POST)
            _log(request, 'edited vehicle', vehicle_id)
            messages.success(request, 'Vehicle saved.' if changed else 'Nothing changed.')
        elif action == 'transfer':
            matches = ca.find_customer(db, request.POST.get('owner'))
            if not matches:
                raise ca.CustomerAdminError('No customer has that email or mobile number.')
            if len(matches) > 1:
                raise ca.CustomerAdminError('More than one customer matches. Use their email instead.')
            res = ca.transfer_vehicle(db, vehicle_id, matches[0].id)
            _log(request, 'moved vehicle', f"{vehicle_id} {res['from']} -> {res['to']}")
            messages.success(request, f"Vehicle moved to {res['to_name'] or 'the new owner'}. Its QR sticker moved with it.")
        elif action == 'unlink_qr':
            qr_id = ca.unlink_vehicle_qr(db, vehicle_id)
            _log(request, 'unlinked QR', f'{qr_id} from {vehicle_id}')
            messages.success(request, f'QR {qr_id} unlinked. Scanning it will open activation again.')
        elif action == 'delete':
            _, cur = ca.get_vehicle(db, vehicle_id)
            reg = str(cur.get('registrationNumber') or 'DELETE')
            typed = (request.POST.get('confirm') or '').replace(' ', '').upper()
            if typed not in (reg.replace(' ', '').upper(), 'DELETE'):
                raise ca.CustomerAdminError(f'Type {reg} to confirm.')
            res = ca.delete_vehicle(db, vehicle_id)
            _log(request, 'deleted vehicle', vehicle_id)
            messages.success(request, f"{res['registration']} deleted and archived."
                             + (' Its QR sticker is free to use again.' if res['qr_freed'] else ''))
            if res['owner']:
                return redirect('customer_detail', user_id=res['owner'])
            return redirect('manage_vehicles')
        else:
            raise ca.CustomerAdminError('Unknown action.')
    except ca.CustomerAdminError as exc:
        messages.error(request, str(exc))
    except Exception:
        logger.exception('vehicle_admin_action %s failed for %s', action, vehicle_id)
        messages.error(request, 'Something went wrong. Try again.')
    return redirect(back)
