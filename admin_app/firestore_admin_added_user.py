"""Canonical Firestore flag for admin-added accounts; remove legacy duplicate keys."""

from firebase_admin import firestore

CANONICAL_ADMIN_ADDED_USER = "adminAddedUser"

_LEGACY_ADMIN_ADDED_USER_KEYS = (
    "admin_added_user",
    "adminUserAdded",
    "admin_user_added",
)


def truthy_admin_added_user_from_json(data, default=False):
    """Parse activate-id JSON for admin-added intent (accepts legacy key names)."""
    if not isinstance(data, dict):
        return default
    for key in (CANONICAL_ADMIN_ADDED_USER, *_LEGACY_ADMIN_ADDED_USER_KEYS):
        if key not in data or data[key] is None:
            continue
        v = data[key]
        if isinstance(v, bool):
            return v
        s = str(v).strip().lower()
        return s in ("true", "1", "yes", "on")
    return default


def admin_added_user_update_payload(value):
    """Firestore update() map: set canonical bool and delete duplicate field names."""
    payload = {CANONICAL_ADMIN_ADDED_USER: bool(value)}
    sentinel = firestore.DELETE_FIELD
    for k in _LEGACY_ADMIN_ADDED_USER_KEYS:
        payload[k] = sentinel
    return payload


def coerced_admin_added_user_from_doc(doc_dict):
    """Effective value when reading a user/vehicle map with mixed legacy keys."""
    if not isinstance(doc_dict, dict):
        return False
    for key in (CANONICAL_ADMIN_ADDED_USER, *_LEGACY_ADMIN_ADDED_USER_KEYS):
        if key not in doc_dict:
            continue
        v = doc_dict[key]
        if isinstance(v, bool):
            return v
        if v is None:
            continue
        s = str(v).strip().lower()
        if s in ("true", "1", "yes", "on"):
            return True
    return False
