"""Admin management for multipurpose QR codes."""

import base64
from io import BytesIO

import qrcode
from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.core.validators import validate_email
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST
from google.cloud.firestore_v1 import FieldFilter

NOT_REGISTERED_EMAIL_MESSAGE = 'This email is not registered with SudoTag.'


def _views():
    from . import views
    return views


def _require_admin(request):
    if not request.session.get('admin'):
        messages.error(request, 'Admin access required')
        return redirect('admin_login')
    return None


def _stamp_label(value):
    if value is None:
        return ''
    if hasattr(value, 'strftime'):
        return value.strftime('%d %b %Y, %H:%M')
    if hasattr(value, 'to_datetime'):
        try:
            return value.to_datetime().strftime('%d %b %Y, %H:%M')
        except Exception:
            return ''
    return ''


def _stamp_sort(value):
    if value is not None and hasattr(value, 'timestamp'):
        try:
            return value.timestamp()
        except Exception:
            return 0
    if value is not None and hasattr(value, 'to_datetime'):
        try:
            return value.to_datetime().timestamp()
        except Exception:
            return 0
    return 0


def _load_snaps():
    views = _views()
    try:
        return list(views.db.collection('multipurpose_qrs').limit(500).stream())
    except Exception:
        return []


def _primary_photo(data):
    raw = data.get('photoUrls') or []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return ''
    for item in raw:
        url = str(item or '').strip()
        if url.startswith('http://') or url.startswith('https://'):
            return url
    return ''


def _row_from_snap(snap):
    data = snap.to_dict() or {}
    if data.get('purpose') not in (None, 'multipurpose'):
        return None
    details = data.get('details') if isinstance(data.get('details'), dict) else {}
    created = data.get('createdDateTime')
    assigned = bool(data.get('isAssigned'))
    return {
        'id': snap.id,
        'qr_type': str(data.get('qrType') or 'Multipurpose QR'),
        'category': str(data.get('category') or ''),
        'category_label': str(data.get('categoryLabel') or ''),
        'title': str(data.get('title') or ''),
        'note': str(data.get('note') or ''),
        'owner': str(data.get('ownerFullName') or ''),
        'assigned': assigned,
        'contact': str(data.get('contactNumber') or ''),
        'user_id': str(data.get('userID') or ''),
        'city': str(details.get('city') or ''),
        'email': str(details.get('emailAddress') or ''),
        'scan_url': str(data.get('scanUrl') or ''),
        'scan_count': int(data.get('scanCount') or 0),
        'last_scanned': _stamp_label(data.get('lastScannedAt')),
        'paused': bool(data.get('contactPaused')),
        'photo_url': _primary_photo(data),
        'created': _stamp_label(created),
        'created_sort': _stamp_sort(created),
        'assigned_at': _stamp_label(data.get('assignedAt')),
        'details': {str(k): str(v) for k, v in details.items() if v},
        'raw': data,
    }


def _category_by_id(category_id):
    views = _views()
    for category in views.MULTIPURPOSE_CATEGORIES:
        if category['id'] == category_id:
            return category
    return None


def find_user_by_registered_email(email):
    """Return (user_id, user_data) for an existing SudoTag account, or (None, None)."""
    views = _views()
    raw = str(email or '').strip()
    if not raw or '@' not in raw:
        return None, None
    candidates = []
    for value in (raw, raw.lower()):
        if value not in candidates:
            candidates.append(value)
    for value in candidates:
        try:
            docs = list(
                views.db.collection('users')
                .where(filter=FieldFilter('emailAddress', '==', value))
                .limit(1)
                .stream()
            )
        except Exception:
            docs = []
        if docs:
            return docs[0].id, docs[0].to_dict() or {}
    try:
        from firebase_admin import auth
        record = auth.get_user_by_email(raw)
    except Exception:
        return None, None
    try:
        snap = views.db.collection('users').document(record.uid).get()
    except Exception:
        return None, None
    if not snap.exists:
        return None, None
    return snap.id, snap.to_dict() or {}


def _user_summary(user_id):
    if not user_id:
        return None
    views = _views()
    try:
        snap = views.db.collection('users').document(user_id).get()
    except Exception:
        return None
    if not snap.exists:
        return None
    data = snap.to_dict() or {}
    return {
        'id': user_id,
        'name': str(data.get('fullName') or ''),
        'email': str(data.get('emailAddress') or ''),
        'phone': str(data.get('contactNumber') or ''),
        'city': str(data.get('city') or ''),
    }


def _qr_png(qr_id, scan_url):
    views = _views()
    if not scan_url:
        scan_url = f"{settings.BASE_DOMAIN}/admin/mp/{qr_id}/"
    qr = qrcode.QRCode(
        version=3,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=12,
        border=2,
    )
    qr.add_data(scan_url)
    qr.make(fit=True)
    image = qr.make_image(fill_color='black', back_color='white')
    try:
        image = views._compose_multipurpose_qr(image)
    except Exception:
        pass
    buffer = BytesIO()
    image.save(buffer, format='PNG')
    return base64.b64encode(buffer.getvalue()).decode('utf-8')


@require_http_methods(['GET'])
def manage_multipurpose_qrs(request):
    gate = _require_admin(request)
    if gate:
        return gate

    status = (request.GET.get('status') or '').strip()
    search_raw = request.GET.get('search') or ''
    search = search_raw.strip().lower()
    rows = []
    for snap in _load_snaps():
        row = _row_from_snap(snap)
        if row is None:
            continue
        rows.append(row)
    active_count = sum(1 for row in rows if row['assigned'])
    inactive_count = len(rows) - active_count
    if status == 'assigned':
        rows = [row for row in rows if row['assigned']]
    elif status == 'unassigned':
        rows = [row for row in rows if not row['assigned']]
    if search:
        filtered = []
        for row in rows:
            haystack = ' '.join([
                row['id'],
                row['title'],
                row['note'],
                row['owner'],
                row['contact'],
                row['category_label'],
                row['category'],
                row['city'],
                row['email'],
                row['user_id'],
            ]).lower()
            if search in haystack:
                filtered.append(row)
        rows = filtered
    rows.sort(key=lambda row: row['created_sort'], reverse=True)

    paginator = Paginator(rows, 20)
    try:
        page = paginator.page(request.GET.get('page') or 1)
    except PageNotAnInteger:
        page = paginator.page(1)
    except EmptyPage:
        page = paginator.page(paginator.num_pages)

    return render(request, 'manage_multipurpose_qrs.html', {
        'rows': page,
        'paginator': paginator,
        'status': status,
        'search': search_raw,
        'total_count': active_count + inactive_count,
        'active_count': active_count,
        'inactive_count': inactive_count,
    })


def _detail_context(row, user, qr_png, form_values=None):
    views = _views()
    values = {
        'category': row['category'],
        'note': row['note'],
        'contactNumber': row['contact'],
        'fullName': row['owner'],
    }
    values.update(row['details'])
    if form_values:
        values.update(form_values)
    return {
        'row': row,
        'user': user,
        'qr_png': qr_png,
        'categories': views.MULTIPURPOSE_CATEGORIES,
        'values': values,
    }


@require_http_methods(['GET', 'POST'])
def manage_multipurpose_qr(request, qr_id):
    gate = _require_admin(request)
    if gate:
        return gate

    views = _views()
    try:
        snap = views.db.collection('multipurpose_qrs').document(qr_id).get()
    except Exception:
        snap = None
    if snap is None or not snap.exists:
        messages.error(request, 'Multipurpose QR not found.')
        return redirect('manage_multipurpose_qrs')
    row = _row_from_snap(snap)
    if row is None:
        messages.error(request, 'This code is not a multipurpose QR.')
        return redirect('manage_multipurpose_qrs')

    if request.method == 'POST':
        action = (request.POST.get('action') or '').strip()
        if action == 'pause':
            if not row['assigned']:
                messages.info(request, 'Activate this QR before pausing contact.')
            else:
                snap.reference.update({'contactPaused': True})
                messages.success(request, 'Contact is paused. Scans still open this tag, without call, message, or push.')
            return redirect('manage_multipurpose_qr', qr_id=qr_id)
        if action == 'resume':
            snap.reference.update({'contactPaused': False})
            messages.success(request, 'Contact is available again.')
            return redirect('manage_multipurpose_qr', qr_id=qr_id)
        if action == 'deactivate':
            if not row['assigned']:
                messages.info(request, 'This QR is already inactive.')
            else:
                snap.reference.update({'isAssigned': False})
                messages.success(request, 'Multipurpose QR marked inactive. Scans will ask for activation again.')
            return redirect('manage_multipurpose_qr', qr_id=qr_id)
        if action == 'save':
            return _save_usage(request, snap, row)
        messages.error(request, 'Unknown action.')
        return redirect('manage_multipurpose_qr', qr_id=qr_id)

    user = _user_summary(row['user_id'])
    png = _qr_png(qr_id, row['scan_url'])
    return render(request, 'manage_multipurpose_qr.html', _detail_context(row, user, png))


def _usage_from_post(request):
    """Validate category usage fields. Returns (update, errors, posted)."""
    views = _views()
    category = _category_by_id((request.POST.get('category') or '').strip())
    posted = {'category': (request.POST.get('category') or '').strip()}
    if category is None:
        return None, ['Choose a category.'], posted

    errors = []
    for field in category['fields']:
        value = str(request.POST.get(field['key']) or '').strip()
        if field['key'] == 'contactNumber':
            digits = views.normalize_phone_number(value)
            if not digits:
                errors.append('Enter a valid 10-digit mobile number.')
            else:
                posted['contactNumber'] = digits
            continue
        if field['key'] == 'note' and len(value) < 2:
            errors.append('Enter the message people will see after scanning.')
            posted['note'] = value
            continue
        if field.get('required') and not value:
            errors.append(f"{field['label']} is required.")
        posted[field['key']] = value

    title = str(posted.get(category['title_field']) or '').strip()
    if len(title) < 2:
        errors.append('The name shown on the QR needs at least 2 characters.')
    if errors:
        return None, errors, posted

    details = {}
    for field in category['fields']:
        key = field['key']
        if key in ('contactNumber', 'note'):
            continue
        value = posted.get(key) or ''
        if value:
            details[key] = value[:200]
    update = {
        'qrType': views.MULTIPURPOSE_QR_TYPE,
        'purpose': 'multipurpose',
        'category': category['id'],
        'categoryLabel': category['label'],
        'title': title[:80],
        'ownerFullName': str(posted.get('fullName') or '').strip()[:80],
        'contactNumber': posted['contactNumber'],
        'details': details,
        'note': str(posted.get('note') or '').strip()[:500],
        'isAssigned': True,
    }
    return update, [], posted


def _save_usage(request, snap, row):
    if not row['assigned']:
        messages.error(request, 'Activate this QR from a scan before editing usage.')
        return redirect('manage_multipurpose_qr', qr_id=row['id'])

    update, errors, posted = _usage_from_post(request)
    if errors:
        for error in errors:
            messages.error(request, error)
        user = _user_summary(row['user_id'])
        png = _qr_png(row['id'], row['scan_url'])
        return render(
            request,
            'manage_multipurpose_qr.html',
            _detail_context(row, user, png, posted),
        )

    snap.reference.update(update)
    messages.success(request, 'Multipurpose QR usage updated.')
    return redirect('manage_multipurpose_qr', qr_id=row['id'])


def inactive_multipurpose_rows():
    rows = []
    for snap in _load_snaps():
        row = _row_from_snap(snap)
        if row is None or row['assigned']:
            continue
        rows.append(row)
    rows.sort(key=lambda row: row['created_sort'], reverse=True)
    return rows


def assign_multipurpose_from_assign_page(request):
    views = _views()
    selected_qr = (request.POST.get('qr_id') or '').strip()
    owner_email = (request.POST.get('owner_email') or request.POST.get('emailAddress') or '').strip()
    update, errors, _posted = _usage_from_post(request)
    back = reverse('assign_qr') + '?qr_kind=multipurpose'
    if selected_qr:
        back += '&qr_id=' + selected_qr
    if not selected_qr:
        errors.append('Choose a multipurpose QR.')
    user_id = None
    user_data = None
    registered_email = ''
    if owner_email:
        try:
            validate_email(owner_email)
        except ValidationError:
            errors.append('Enter a valid email address.')
        else:
            user_id, user_data = find_user_by_registered_email(owner_email)
            if not user_id:
                errors.append(NOT_REGISTERED_EMAIL_MESSAGE)
            else:
                registered_email = str((user_data or {}).get('emailAddress') or owner_email).strip()
    elif update is not None:
        errors.append(NOT_REGISTERED_EMAIL_MESSAGE)
    snap = None
    if selected_qr:
        try:
            snap = views.db.collection('multipurpose_qrs').document(selected_qr).get()
        except Exception:
            snap = None
        if snap is None or not snap.exists:
            errors.append('Multipurpose QR not found.')
        else:
            data = snap.to_dict() or {}
            if data.get('purpose') not in (None, 'multipurpose'):
                errors.append('That code is not a multipurpose QR.')
            elif data.get('isAssigned'):
                errors.append('This multipurpose QR is already active.')
    if errors or update is None or not user_id:
        for error in errors:
            messages.error(request, error)
        return redirect(back)
    from firebase_admin import firestore
    details = update.get('details') if isinstance(update.get('details'), dict) else {}
    details['emailAddress'] = registered_email
    update['details'] = details
    update['userID'] = user_id
    update['ownerEmail'] = registered_email
    update['assignedAt'] = firestore.SERVER_TIMESTAMP
    update['assignedBy'] = 'admin'
    snap.reference.update(update)
    messages.success(
        request,
        f'Multipurpose QR {selected_qr} assigned to {registered_email}.',
    )
    return redirect('manage_multipurpose_qr', qr_id=selected_qr)


@require_http_methods(['GET'])
def lookup_registered_user(request):
    gate = _require_admin(request)
    if gate:
        return JsonResponse({'ok': False, 'message': 'Admin access required.'}, status=401)
    email = (request.GET.get('email') or '').strip()
    try:
        validate_email(email)
    except ValidationError:
        return JsonResponse({'ok': False, 'message': 'Enter a valid email address.'}, status=400)
    user_id, data = find_user_by_registered_email(email)
    if not user_id:
        return JsonResponse({'ok': False, 'message': NOT_REGISTERED_EMAIL_MESSAGE})
    return JsonResponse({
        'ok': True,
        'user': {
            'id': user_id,
            'name': str((data or {}).get('fullName') or ''),
            'email': str((data or {}).get('emailAddress') or email).strip(),
            'phone': str((data or {}).get('contactNumber') or ''),
            'city': str((data or {}).get('city') or ''),
        },
    })


def assign_multipurpose_qr(request):
    gate = _require_admin(request)
    if gate:
        return gate
    qr_id = (request.GET.get('qr_id') or '').strip()
    url = reverse('assign_qr') + '?qr_kind=multipurpose'
    if qr_id:
        url += '&qr_id=' + qr_id
    return redirect(url)


@require_POST
def delete_multipurpose_qr(request, qr_id):
    gate = _require_admin(request)
    if gate:
        return gate
    views = _views()
    try:
        snap = views.db.collection('multipurpose_qrs').document(qr_id).get()
    except Exception:
        snap = None
    if snap is None or not snap.exists:
        messages.error(request, 'Multipurpose QR not found.')
        return redirect('manage_multipurpose_qrs')
    data = snap.to_dict() or {}
    if data.get('isAssigned'):
        messages.error(request, 'Deactivate this QR before deleting it.')
        return redirect('manage_multipurpose_qr', qr_id=qr_id)
    snap.reference.delete()
    messages.success(request, f'Deleted multipurpose QR {qr_id}.')
    return redirect('manage_multipurpose_qrs')
