"""
App Version Management: SudoTag Android / iOS update policy.

Source of truth is Firestore ``appConfig/{android|ios}``; the Flutter app reads
it directly (``lib/service/app_update/app_update_policy.dart`` in the mobile
repo). The rules in :func:`decide_update` mirror ``decideUpdate`` there; keep
them in step.

Every publish also appends ``appConfig/{platform}/releases/{autoId}`` (release
history). Firestore rules allow public read of ``appConfig/{platform}`` and no
client writes; history, ``app_update_events`` and user counts are read here
through the Admin SDK only.

Pure helpers (validation, comparison, decisions, API payloads) take no
Firestore client so they are unit-tested without network.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Optional
from urllib.parse import urlparse

PLATFORMS = ('android', 'ios')
UPDATE_TYPES = ('flexible', 'immediate')

DEFAULT_STORE_URLS = {
    'android': 'https://play.google.com/store/apps/details?id=com.sudotag.sudo',
    'ios': 'https://apps.apple.com/app/id6761091033',
}
STORE_HOSTS = {
    'android': ('play.google.com',),
    'ios': ('apps.apple.com', 'itunes.apple.com'),
}

CONFIG_COLLECTION = 'appConfig'
RELEASES_SUBCOLLECTION = 'releases'
EVENTS_COLLECTION = 'app_update_events'

_VERSION_RE = re.compile(r'^\d+(\.\d+){0,3}$')
MAX_NOTES = 4000
MAX_TITLE = 80
MAX_MESSAGE = 400
MAX_BUILD = 2_100_000_000  # Play versionCode limit


class UnknownPlatform(ValueError):
    pass


def check_platform(platform: str) -> str:
    p = (platform or '').strip().lower()
    if p not in PLATFORMS:
        raise UnknownPlatform(f'Unknown platform: {platform!r}')
    return p


# ── Versions and decisions (mirror of the app) ───────────────────────────────

def compare_versions(a: str, b: str) -> int:
    """Numeric dotted compare: 1.10.0 > 1.9.9, 1.2 == 1.2.0; '+'/'-' suffixes ignored."""
    def parts(v: str) -> list[int]:
        core = re.split(r'[+-]', (v or '').strip())[0]
        out = []
        for p in core.split('.'):
            m = re.match(r'^\d+', p.strip())
            out.append(int(m.group()) if m else 0)
        return out

    pa, pb = parts(a), parts(b)
    for i in range(max(len(pa), len(pb))):
        x = pa[i] if i < len(pa) else 0
        y = pb[i] if i < len(pb) else 0
        if x != y:
            return -1 if x < y else 1
    return 0


def _as_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return 0
    return 0


def _as_bool(value: Any, fallback: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        s = value.strip().lower()
        if s in ('true', '1', 'yes', 'on'):
            return True
        if s in ('false', '0', 'no', 'off'):
            return False
    return fallback


def _is_below(installed_build: int, installed_version: str, *, build: int, version: str) -> bool:
    if build > 0 and installed_build > 0:
        return installed_build < build
    if version and installed_version:
        return compare_versions(installed_version, version) < 0
    return False


def decide_update(installed_build: int, installed_version: str, config: Optional[dict]) -> str:
    """'none' | 'optional' | 'mandatory' for an installed app and a stored config."""
    if not config or not _as_bool(config.get('updateEnabled'), True):
        return 'none'
    if _is_below(installed_build, installed_version,
                 build=_as_int(config.get('minSupportedBuild')),
                 version=str(config.get('minSupportedVersion') or '').strip()):
        return 'mandatory'
    if not _is_below(installed_build, installed_version,
                     build=_as_int(config.get('latestBuild')),
                     version=str(config.get('latestVersion') or '').strip()):
        return 'none'
    return 'mandatory' if _as_bool(config.get('forceUpdate'), False) else 'optional'


# ── Validation ───────────────────────────────────────────────────────────────

def validate_config(platform: str, data: dict) -> tuple[dict, dict]:
    """Validates admin input. Returns (clean Firestore fields, errors by field).

    Accepts the form / JSON field names used by the panel and the REST API
    (snake_case as in the API docs, or the Firestore camelCase names).
    """
    platform = check_platform(platform)
    errors: dict[str, str] = {}

    def pick(*names, default=None):
        for n in names:
            if n in data and data[n] is not None:
                return data[n]
        return default

    latest_version = str(pick('latest_version', 'latestVersion', default='')).strip()
    if not _VERSION_RE.match(latest_version):
        errors['latest_version'] = 'Use a version like 1.1.54.'

    def parse_build(raw, field, required):
        s = str(raw if raw is not None else '').strip()
        if not s:
            if required:
                errors[field] = 'Required.'
            return 0
        if not s.isdigit():
            errors[field] = 'Must be a whole number.'
            return 0
        n = int(s)
        if n > MAX_BUILD:
            errors[field] = 'Too large.'
        return n

    latest_build = parse_build(pick('latest_build', 'latestBuild'), 'latest_build', True)
    if 'latest_build' not in errors and latest_build < 1:
        errors['latest_build'] = 'Must be 1 or more.'

    min_version = str(pick('minimum_supported_version', 'minSupportedVersion', default='')).strip()
    if min_version and not _VERSION_RE.match(min_version):
        errors['minimum_supported_version'] = 'Use a version like 1.1.40, or leave empty.'
    min_build = parse_build(pick('minimum_supported_build', 'minSupportedBuild'),
                            'minimum_supported_build', False)

    if 'latest_build' not in errors and 'minimum_supported_build' not in errors \
            and min_build > latest_build:
        errors['minimum_supported_build'] = 'Cannot be higher than the latest build.'
    if min_version and not errors.get('minimum_supported_version') \
            and not errors.get('latest_version') \
            and compare_versions(min_version, latest_version) > 0:
        errors['minimum_supported_version'] = 'Cannot be higher than the latest version.'

    update_type = str(pick('update_type', 'updateType', default='flexible')).strip().lower()
    if update_type not in UPDATE_TYPES:
        errors['update_type'] = 'Choose flexible or immediate.'

    store_url = str(pick('store_url', 'storeUrl', default='')).strip() or DEFAULT_STORE_URLS[platform]
    parsed = urlparse(store_url)
    if parsed.scheme != 'https' or parsed.hostname not in STORE_HOSTS[platform]:
        errors['store_url'] = (
            'Use the Google Play listing (https://play.google.com/...).'
            if platform == 'android'
            else 'Use the App Store listing (https://apps.apple.com/...).'
        )

    release_notes = str(pick('release_notes', 'releaseNotes', default='')).strip()
    if len(release_notes) > MAX_NOTES:
        errors['release_notes'] = f'Keep release notes under {MAX_NOTES} characters.'
    title = str(pick('update_title', 'updateTitle', default='')).strip()
    if len(title) > MAX_TITLE:
        errors['update_title'] = f'Keep the title under {MAX_TITLE} characters.'
    message = str(pick('update_message', 'updateMessage', default='')).strip()
    if len(message) > MAX_MESSAGE:
        errors['update_message'] = f'Keep the message under {MAX_MESSAGE} characters.'

    clean = {
        'platform': platform,
        'latestVersion': latest_version,
        'latestBuild': latest_build,
        'minSupportedVersion': min_version,
        'minSupportedBuild': min_build,
        'forceUpdate': _as_bool(pick('force_update', 'forceUpdate'), False),
        'updateEnabled': _as_bool(pick('update_enabled', 'updateEnabled'), True),
        'updateType': update_type if update_type in UPDATE_TYPES else 'flexible',
        'releaseNotes': release_notes,
        'storeUrl': store_url,
        'updateTitle': title,
        'updateMessage': message,
    }
    return clean, errors


# ── API payloads ─────────────────────────────────────────────────────────────

def _iso(value: Any) -> Optional[str]:
    if isinstance(value, datetime):
        return value.isoformat()
    return None


def version_check_payload(platform: str, config: Optional[dict], *,
                          installed_build: int = 0, installed_version: str = '') -> dict:
    """Response of GET /api/v1/app/version-check. ``update_available`` and
    ``force_update`` are computed here from the installed build, not trusted
    from the client."""
    platform = check_platform(platform)
    c = config or {}
    decision = decide_update(installed_build, installed_version, c) if config else 'none'
    enabled = bool(config) and _as_bool(c.get('updateEnabled'), True)
    return {
        'platform': platform,
        'update_enabled': enabled,
        'latest_version': str(c.get('latestVersion') or ''),
        'latest_build': _as_int(c.get('latestBuild')),
        'minimum_supported_version': str(c.get('minSupportedVersion') or ''),
        'minimum_supported_build': _as_int(c.get('minSupportedBuild')),
        'update_available': decision != 'none',
        'force_update': decision == 'mandatory',
        'update_type': str(c.get('updateType') or 'flexible'),
        'release_notes': str(c.get('releaseNotes') or ''),
        'store_url': str(c.get('storeUrl') or DEFAULT_STORE_URLS[platform]),
        'published_at': _iso(c.get('publishedAt')),
    }


def admin_config_payload(platform: str, config: Optional[dict]) -> dict:
    """Admin API view of a stored config (``id`` is the platform)."""
    c = config or {}
    return {
        'id': platform,
        'platform': platform,
        'exists': config is not None,
        'update_enabled': _as_bool(c.get('updateEnabled'), True) if config else False,
        'latest_version': str(c.get('latestVersion') or ''),
        'latest_build': _as_int(c.get('latestBuild')),
        'minimum_supported_version': str(c.get('minSupportedVersion') or ''),
        'minimum_supported_build': _as_int(c.get('minSupportedBuild')),
        'force_update': _as_bool(c.get('forceUpdate'), False),
        'update_type': str(c.get('updateType') or 'flexible'),
        'release_notes': str(c.get('releaseNotes') or ''),
        'store_url': str(c.get('storeUrl') or DEFAULT_STORE_URLS[platform]),
        'update_title': str(c.get('updateTitle') or ''),
        'update_message': str(c.get('updateMessage') or ''),
        'published_at': _iso(c.get('publishedAt')),
        'published_by': str(c.get('publishedBy') or ''),
    }


# ── Firestore ────────────────────────────────────────────────────────────────

def get_db():
    from firebase_admin import firestore
    return firestore.client()


def get_config(db, platform: str) -> Optional[dict]:
    snap = db.collection(CONFIG_COLLECTION).document(check_platform(platform)).get()
    return snap.to_dict() if snap.exists else None


def publish_config(db, platform: str, clean: dict, *, admin_email: str = '', admin_uid: str = '') -> None:
    """Replaces appConfig/{platform} and appends the release history entry."""
    from firebase_admin import firestore

    platform = check_platform(platform)
    doc = {k: v for k, v in clean.items() if k != 'platform'}
    doc.update({
        'publishedAt': firestore.SERVER_TIMESTAMP,
        'publishedBy': admin_email or admin_uid or 'admin',
    })
    config_ref = db.collection(CONFIG_COLLECTION).document(platform)
    history_ref = config_ref.collection(RELEASES_SUBCOLLECTION).document()
    batch = db.batch()
    batch.set(config_ref, doc)
    batch.set(history_ref, dict(doc, adminUid=admin_uid or ''))
    batch.commit()


def list_releases(db, platform: str, limit: int = 20) -> list[dict]:
    from firebase_admin import firestore

    ref = (db.collection(CONFIG_COLLECTION).document(check_platform(platform))
           .collection(RELEASES_SUBCOLLECTION)
           .order_by('publishedAt', direction=firestore.Query.DESCENDING)
           .limit(limit))
    return [dict(d.to_dict() or {}, id=d.id) for d in ref.stream()]


def _count(query) -> int:
    result = query.count().get()
    # [[AggregationResult]] in google-cloud-firestore 2.x
    return int(result[0][0].value)


def adoption_stats(db, platform: str, config: Optional[dict]) -> dict:
    """User counts from users/{uid}.appPlatform / appBuild (written by the app
    from this release on). Older builds don't report, so they are counted as
    'not reported'."""
    from google.cloud.firestore_v1.base_query import FieldFilter

    platform = check_platform(platform)
    users = db.collection('users')
    on_platform = users.where(filter=FieldFilter('appPlatform', '==', platform))
    reporting = _count(on_platform)
    latest = _as_int((config or {}).get('latestBuild'))
    minimum = _as_int((config or {}).get('minSupportedBuild'))
    on_latest = _count(on_platform.where(filter=FieldFilter('appBuild', '>=', latest))) if latest else 0
    below_min = _count(on_platform.where(filter=FieldFilter('appBuild', '<', minimum))) if minimum else 0
    outdated = reporting - on_latest if latest else 0
    return {
        'reporting': reporting,
        'on_latest': on_latest,
        'outdated': max(outdated, 0),
        'below_minimum': below_min,
        'adoption_pct': round(100.0 * on_latest / reporting, 1) if reporting and latest else None,
    }


def total_users(db) -> int:
    return _count(db.collection('users'))


def recent_events(db, platform: Optional[str] = None, limit: int = 50, errors_only: bool = False) -> list[dict]:
    from firebase_admin import firestore
    from google.cloud.firestore_v1.base_query import FieldFilter

    q = db.collection(EVENTS_COLLECTION)
    if platform:
        q = q.where(filter=FieldFilter('platform', '==', check_platform(platform)))
    q = q.order_by('createdAt', direction=firestore.Query.DESCENDING).limit(limit * 3 if errors_only else limit)
    rows = [dict(d.to_dict() or {}, id=d.id) for d in q.stream()]
    if errors_only:
        rows = [r for r in rows if r.get('error') or str(r.get('event', '')).endswith(('failed', 'unavailable'))]
    return rows[:limit]
