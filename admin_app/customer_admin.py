"""Complete admin workflows for customers and vehicles.

Every change keeps the linked records consistent:
- editing a customer updates their vehicles (owner name / phone shown on
  QR scans) and their Firebase sign-in email / phone;
- editing a vehicle checks the registration is not already used;
- moving a vehicle to another customer moves its QR too and recounts both
  customers' vehicles;
- deleting a vehicle archives it, frees its QR sticker (scans open
  activation again) and recounts the owner's vehicles;
- deleting a customer archives them and their vehicles, frees every QR
  sticker and Smart Tag they had (clearing their personal details from the
  tags), removes their sign-in account and finally their profile.

Functions take the Firestore client so tests can pass a fake one.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from typing import Iterable, List, Optional, Tuple

from firebase_admin import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

logger = logging.getLogger(__name__)

DELETE = firestore.DELETE_FIELD
NOW = firestore.SERVER_TIMESTAMP

BLOOD_GROUPS = ('A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-')
EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$')
REG_RE = re.compile(r'^[A-Z0-9]{4,12}$')
VEHICLE_TYPES = ('Car', 'Bike', 'Scooter', 'Auto', 'Lorry', 'Truck', 'Bus', 'Van', 'Tractor', 'Other')

SMART_TAG_PERSONAL_FIELDS = (
    'userID', 'ownerFullName', 'ownerEmail', 'contactNumber', 'details', 'note',
    'photoUrls', 'links', 'title', 'category', 'categoryLabel', 'assignedAt', 'contactPaused',
)


class CustomerAdminError(ValueError):
    """Message is safe to show to the admin."""


# ─── Validation ─────────────────────────────────────────────────────────────

def clean_name(raw: str) -> str:
    name = ' '.join(str(raw or '').split())
    if len(name) < 2 or len(name) > 80:
        raise CustomerAdminError('Enter a name between 2 and 80 characters.')
    return name


def clean_email(raw: str) -> str:
    email = str(raw or '').strip()
    if not EMAIL_RE.match(email) or len(email) > 120:
        raise CustomerAdminError('Enter a valid email address.')
    return email


def clean_phone(raw: str, *, required: bool = True, label: str = 'mobile number') -> str:
    digits = re.sub(r'\D', '', str(raw or ''))
    if digits.startswith('91') and len(digits) == 12:
        digits = digits[2:]
    if digits.startswith('0') and len(digits) == 11:
        digits = digits[1:]
    if not digits and not required:
        return ''
    if len(digits) != 10 or digits[0] not in '6789':
        raise CustomerAdminError(f'Enter a valid 10-digit Indian {label}.')
    return digits


def clean_registration(raw: str) -> str:
    reg = re.sub(r'[^A-Za-z0-9]', '', str(raw or '')).upper()
    if not REG_RE.match(reg):
        raise CustomerAdminError('Enter the registration number, e.g. KL10AB1234.')
    return reg


def clean_year(raw: str) -> str:
    s = str(raw or '').strip()
    if not s:
        return ''
    if not s.isdigit() or not (1950 <= int(s) <= dt.date.today().year + 1):
        raise CustomerAdminError('Enter a valid year of manufacture.')
    return s


# ─── Lookups ────────────────────────────────────────────────────────────────

def _where(db, collection: str, field: str, value) -> list:
    return list(db.collection(collection).where(filter=FieldFilter(field, '==', value)).stream())


def vehicles_of(db, uid: str) -> list:
    return _where(db, 'vehicles', 'ownerId', uid)


def qrs_of(db, uid: str) -> list:
    return _where(db, 'qrcodes', 'userID', uid)


def smart_tags_of(db, uid: str) -> list:
    return _where(db, 'multipurpose_qrs', 'userID', uid)


def orders_of(db, uid: str) -> list:
    return _where(db, 'orders', 'userId', uid)


def refresh_vehicle_count(db, uid: str) -> int:
    n = len(vehicles_of(db, uid))
    ref = db.collection('users').document(uid)
    if ref.get().exists:
        ref.update({'vehicleCount': n})
    return n


def _taken(db, collection: str, field: str, value, except_id: str) -> bool:
    return any(d.id != except_id for d in _where(db, collection, field, value))


# ─── Archive (Django models used by the Archived Data screen) ──────────────

def _archive_user(uid: str, data: dict):
    from .models import ArchivedUser
    from .views import _safe_str, _serialize_firestore_data, _to_datetime_or_none
    ArchivedUser.objects.update_or_create(user_id=uid, defaults={
        'email': _safe_str(data.get('emailAddress'), ''),
        'full_name': _safe_str(data.get('fullName'), ''),
        'phone': _safe_str(data.get('contactNumber'), ''),
        'original_created_at': _to_datetime_or_none(data.get('createdAt')),
        'raw': _serialize_firestore_data(data) or {},
    })


def _archive_vehicle(vehicle_id: str, data: dict):
    from .models import ArchivedVehicle
    from .views import _safe_str, _serialize_firestore_data, _to_datetime_or_none
    ArchivedVehicle.objects.update_or_create(vehicle_id=vehicle_id, defaults={
        'owner_id': _safe_str(data.get('ownerId'), ''),
        'registration_number': _safe_str(data.get('registrationNumber'), ''),
        'make': _safe_str(data.get('make'), ''),
        'model': _safe_str(data.get('model'), ''),
        'vehicle_type': _safe_str(data.get('vehicleType'), ''),
        'owner_contact': _safe_str(data.get('ownerContact'), ''),
        'qr_code_id': _safe_str(data.get('qrCodeId') or data.get('qrId'), ''),
        'original_created_at': _to_datetime_or_none(data.get('createdAt')),
        'raw': _serialize_firestore_data(data) or {},
    })


# ─── Customers ──────────────────────────────────────────────────────────────

def update_customer(db, uid: str, form: dict, *, auth_module=None) -> dict:
    """Validate and save a customer's details, then keep linked records in step.
    Returns {'changed': [...], 'vehicles_updated': n}."""
    ref = db.collection('users').document(uid)
    snap = ref.get()
    if not snap.exists:
        raise CustomerAdminError('Customer not found.')
    cur = snap.to_dict() or {}

    name = clean_name(form.get('fullName'))
    email = clean_email(form.get('emailAddress'))
    phone = clean_phone(form.get('contactNumber'))
    city = ' '.join(str(form.get('city') or '').split())[:60]
    blood = str(form.get('bloodGroup') or '').strip().upper()
    if blood and blood not in BLOOD_GROUPS:
        raise CustomerAdminError('Choose a valid blood group.')
    emergency = clean_phone(form.get('defaultEmergencyContact'), required=False, label='emergency contact')
    if emergency and emergency == phone:
        raise CustomerAdminError("The emergency contact can't be the customer's own number.")

    if email.lower() != str(cur.get('emailAddress') or '').lower():
        if _taken(db, 'users', 'emailAddress', email, uid) or _taken(db, 'users', 'emailAddress', email.lower(), uid):
            raise CustomerAdminError('Another customer already uses this email.')
    if phone != re.sub(r'\D', '', str(cur.get('contactNumber') or ''))[-10:]:
        if _taken(db, 'users', 'contactNumber', phone, uid):
            raise CustomerAdminError('Another customer already uses this mobile number.')

    new = {'fullName': name, 'emailAddress': email, 'contactNumber': phone, 'city': city,
           'bloodGroup': blood, 'defaultEmergencyContact': emergency}
    changed = [k for k, v in new.items() if str(cur.get(k) or '') != v]
    if not changed:
        return {'changed': [], 'vehicles_updated': 0}

    # Sign-in account first: if Firebase refuses (e.g. email used by another
    # account) nothing else changes.
    if auth_module is not None and ({'emailAddress', 'contactNumber'} & set(changed)):
        kwargs = {}
        if 'emailAddress' in changed:
            kwargs['email'] = email
        if 'contactNumber' in changed:
            kwargs['phone_number'] = '+91' + phone
        try:
            auth_module.update_user(uid, **kwargs)
        except Exception as exc:  # firebase_admin.auth errors
            name_ = type(exc).__name__
            if name_ == 'UserNotFoundError':
                pass  # profile without a sign-in account: just update the profile
            elif name_ in ('EmailAlreadyExistsError', 'PhoneNumberAlreadyExistsError'):
                raise CustomerAdminError('That email or mobile number is already used by another sign-in account.')
            else:
                logger.exception('auth update failed for %s', uid)
                raise CustomerAdminError('Could not update the sign-in account. Nothing was changed.')

    ref.update({**{k: new[k] for k in changed}, 'updatedAt': NOW, 'adminEditedAt': NOW})

    vehicles_updated = 0
    if {'fullName', 'contactNumber'} & set(changed):
        for v in vehicles_of(db, uid):
            v.reference.update({'ownerFullName': name, 'ownerContact': phone})
            vehicles_updated += 1
        if 'fullName' in changed:
            old = str(cur.get('fullName') or '')
            for t in smart_tags_of(db, uid):
                if str((t.to_dict() or {}).get('ownerFullName') or '') == old:
                    t.reference.update({'ownerFullName': name})
    return {'changed': changed, 'vehicles_updated': vehicles_updated}


def delete_customer(db, uid: str, *, auth_module=None, is_protected=None) -> dict:
    """Archive and remove a customer with everything linked to them."""
    ref = db.collection('users').document(uid)
    snap = ref.get()
    data = (snap.to_dict() or {}) if snap.exists else {}
    if is_protected and is_protected(data):
        raise CustomerAdminError('Admin accounts cannot be deleted here.')

    vehicles = vehicles_of(db, uid)
    _archive_user(uid, data)
    for v in vehicles:
        _archive_vehicle(v.id, v.to_dict() or {})

    freed_qrs = 0
    for v in vehicles:
        freed_qrs += _free_vehicle_qr(db, v.id, v.to_dict() or {})
        v.reference.delete()
    # QR codes still pointing at this customer (e.g. vehicle already gone).
    for q in qrs_of(db, uid):
        if (q.to_dict() or {}).get('isAssigned'):
            q.reference.update(_qr_reset())
            freed_qrs += 1
    tags = 0
    for t in smart_tags_of(db, uid):
        t.reference.update({'isAssigned': False, **{f: DELETE for f in SMART_TAG_PERSONAL_FIELDS},
                            'updatedAt': NOW})
        tags += 1

    auth_deleted = False
    if auth_module is not None:
        try:
            auth_module.delete_user(uid)
            auth_deleted = True
        except Exception as exc:
            if type(exc).__name__ != 'UserNotFoundError':
                logger.exception('auth delete failed for %s', uid)
                raise CustomerAdminError(
                    'The customer was archived and their vehicles and tags were freed, '
                    "but their sign-in account couldn't be deleted. Try again.")
    if snap.exists:
        ref.delete()
    return {'vehicles': len(vehicles), 'qrs_freed': freed_qrs, 'smart_tags_freed': tags, 'auth_deleted': auth_deleted}


# ─── Vehicles ───────────────────────────────────────────────────────────────

def _qr_reset() -> dict:
    return {'isAssigned': False, 'userID': DELETE, 'vehicleID': DELETE, 'assignedAt': DELETE,
            'partnerId': DELETE, 'lastUpdated': NOW}


def _free_vehicle_qr(db, vehicle_id: str, vehicle: dict) -> int:
    """Return the vehicle's QR to the unused pool, if it still points at it."""
    qr_id = str(vehicle.get('qrCodeId') or '').strip()
    if not qr_id:
        return 0
    qref = db.collection('qrcodes').document(qr_id)
    qs = qref.get()
    if not qs.exists:
        return 0
    if str((qs.to_dict() or {}).get('vehicleID') or '') != vehicle_id:
        return 0
    # Duplicate vehicle records can share one sticker: hand it to the copy
    # that remains instead of freeing a sticker that is still in use.
    for other in _where(db, 'vehicles', 'qrCodeId', qr_id):
        if other.id != vehicle_id:
            qref.update({'vehicleID': other.id,
                         'userID': (other.to_dict() or {}).get('ownerId') or DELETE,
                         'lastUpdated': NOW})
            return 0
    qref.update(_qr_reset())
    return 1


def duplicate_registrations(vehicles: Iterable[dict]) -> List[str]:
    """Registration numbers that appear on more than one of these vehicles."""
    seen, dupes = set(), []
    for v in vehicles:
        reg = re.sub(r'[^A-Z0-9]', '', str(v.get('registrationNumber') or '').upper())
        if reg and reg in seen and reg not in dupes:
            dupes.append(reg)
        seen.add(reg)
    return dupes


def get_vehicle(db, vehicle_id: str) -> Tuple[object, dict]:
    ref = db.collection('vehicles').document(vehicle_id)
    snap = ref.get()
    if not snap.exists:
        raise CustomerAdminError('Vehicle not found.')
    return ref, (snap.to_dict() or {})


def update_vehicle(db, vehicle_id: str, form: dict) -> List[str]:
    ref, cur = get_vehicle(db, vehicle_id)
    reg = clean_registration(form.get('registrationNumber'))
    if reg != str(cur.get('registrationNumber') or '').upper() and _taken(db, 'vehicles', 'registrationNumber', reg, vehicle_id):
        raise CustomerAdminError(f'{reg} is already registered on another vehicle.')
    vtype = str(form.get('vehicleType') or '').strip().title()
    if vtype not in VEHICLE_TYPES:
        raise CustomerAdminError('Choose the vehicle type.')
    make = ' '.join(str(form.get('make') or '').split())[:40]
    model = ' '.join(str(form.get('model') or '').split())[:60]
    if not make:
        raise CustomerAdminError('Enter the make, e.g. Maruti.')
    new = {'registrationNumber': reg, 'vehicleType': vtype, 'make': make, 'model': model,
           'yearOfManufacturing': clean_year(form.get('yearOfManufacturing'))}
    changed = [k for k, v in new.items() if str(cur.get(k) or '') != v]
    if changed:
        ref.update({**{k: new[k] for k in changed}, 'updatedAt': NOW, 'adminEditedAt': NOW})
    return changed


def transfer_vehicle(db, vehicle_id: str, new_owner_uid: str) -> dict:
    ref, cur = get_vehicle(db, vehicle_id)
    old_owner = str(cur.get('ownerId') or '')
    if new_owner_uid == old_owner:
        raise CustomerAdminError('This vehicle already belongs to that customer.')
    owner_snap = db.collection('users').document(new_owner_uid).get()
    if not owner_snap.exists:
        raise CustomerAdminError('New owner not found.')
    owner = owner_snap.to_dict() or {}
    ref.update({
        'ownerId': new_owner_uid,
        'ownerFullName': owner.get('fullName') or '',
        'ownerContact': owner.get('contactNumber') or '',
        # Family-member drivers belong to the old owner's family.
        'assignedFamilyMemberId': None, 'assignedFamilyMemberName': None,
        'assignedFamilyMemberContact': None, 'assignedUntil': None,
        'updatedAt': NOW, 'adminTransferredAt': NOW,
    })
    qr_id = str(cur.get('qrCodeId') or '').strip()
    if qr_id:
        qref = db.collection('qrcodes').document(qr_id)
        qs = qref.get()
        if qs.exists and str((qs.to_dict() or {}).get('vehicleID') or '') == vehicle_id:
            qref.update({'userID': new_owner_uid, 'lastUpdated': NOW})
    counts = {'new': refresh_vehicle_count(db, new_owner_uid)}
    if old_owner:
        counts['old'] = refresh_vehicle_count(db, old_owner)
    return {'from': old_owner, 'to': new_owner_uid, 'to_name': owner.get('fullName') or '', **counts}


def unlink_vehicle_qr(db, vehicle_id: str) -> Optional[str]:
    ref, cur = get_vehicle(db, vehicle_id)
    qr_id = str(cur.get('qrCodeId') or '').strip()
    if not qr_id:
        raise CustomerAdminError('This vehicle has no QR sticker linked.')
    _free_vehicle_qr(db, vehicle_id, cur)
    ref.update({'qrCodeId': DELETE, 'isQrGenerated': False, 'updatedAt': NOW})
    return qr_id


def delete_vehicle(db, vehicle_id: str) -> dict:
    ref, cur = get_vehicle(db, vehicle_id)
    _archive_vehicle(vehicle_id, cur)
    freed = _free_vehicle_qr(db, vehicle_id, cur)
    ref.delete()
    owner = str(cur.get('ownerId') or '')
    count = refresh_vehicle_count(db, owner) if owner else None
    return {'registration': cur.get('registrationNumber') or vehicle_id, 'qr_freed': bool(freed),
            'owner': owner, 'owner_vehicle_count': count}


def find_customer(db, query: str) -> list:
    """Customers whose email or mobile matches exactly (for 'move to owner')."""
    q = str(query or '').strip()
    if not q:
        return []
    found = {}
    if '@' in q:
        for value in {q, q.lower()}:
            for d in _where(db, 'users', 'emailAddress', value):
                found[d.id] = d
    else:
        try:
            phone = clean_phone(q)
        except CustomerAdminError:
            return []
        for value in (phone, '+91' + phone):
            for d in _where(db, 'users', 'contactNumber', value):
                found[d.id] = d
    return list(found.values())
