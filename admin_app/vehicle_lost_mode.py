"""
Vehicle Lost Mode — mirrors Flutter Vehicle.isLostMode on vehicles/{id}.

Canonical Firestore fields (per-vehicle, written by the mobile app):
  - isLostMode          bool
  - lostModeEnabledAt   Timestamp | null  (set on enable, cleared on disable)

Web QR scanners can submit a Lost Mode *sighting* with approximate location
and optional photos. Photos go to Cloudinary; the sighting is stored in
``lostModeSightings`` and the owner gets a push + inbox row.
"""

from __future__ import annotations

import base64
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

logger = logging.getLogger(__name__)

BANNER_TITLE = 'Vehicle reported missing'
BANNER_BODY = (
    'The owner has enabled Lost Mode. If you see this vehicle, please notify '
    'them — your tip can help with recovery.'
)
BADGE_LABEL = 'REPORTED MISSING'
TIP_REASON = 'I spotted this vehicle'
TIP_CTA_TITLE = 'Tip owner — I spotted this vehicle'
TIP_CTA_SUB = 'Send a tip to help recover this vehicle'
REASONS_HEADING = 'Help recover this vehicle'
REASONS_LEAD = 'Tip the owner — choose how you spotted this vehicle, or pick another reason.'

AUTO_PUSH_TITLE = 'Lost Mode — Vehicle spotted'
AUTO_PUSH_BODY = (
    'Someone scanned your SUDO Tag. Your vehicle was spotted while Lost Mode is on.'
)
AUTO_PUSH_SENT_NOTICE = (
    'Owner notified automatically on their phone — thank you for helping.'
)

MAX_SIGHTING_PHOTOS = 3
MAX_PHOTO_BYTES = 450_000
# ~110 m grid — prefer approximate area over exact pin (privacy).
COORD_DECIMALS = 3

_DATA_URL_RE = re.compile(
    r'^data:(image/(?:jpeg|jpg|png|webp));base64,(.+)$',
    re.IGNORECASE | re.DOTALL,
)


def _truthy_bool(raw: Any) -> bool:
    if raw is True:
        return True
    if raw is False or raw is None:
        return False
    if isinstance(raw, (int, float)):
        return raw == 1
    if isinstance(raw, str):
        return raw.strip().lower() in ('1', 'true', 'yes', 'on')
    return bool(raw)


def _format_enabled_at(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, 'isoformat'):
        try:
            return value.isoformat()
        except Exception:
            pass
    if hasattr(value, 'timestamp'):
        try:
            return datetime.utcfromtimestamp(float(value.timestamp())).isoformat() + 'Z'
        except Exception:
            pass
    s = str(value).strip()
    return s or None


def parse_vehicle_lost_mode(vehicle_data: dict | None) -> dict:
    """
    Build a template-safe Lost Mode view from a vehicles/{id} dict.

    Always returns display strings so templates can branch on is_lost_mode only.
    """
    data = vehicle_data if isinstance(vehicle_data, dict) else {}
    is_lost = _truthy_bool(data.get('isLostMode'))
    enabled_at = _format_enabled_at(data.get('lostModeEnabledAt')) if is_lost else None
    return {
        'is_lost_mode': is_lost,
        'isLostMode': is_lost,
        'lost_mode_enabled_at': enabled_at,
        'lostModeEnabledAt': enabled_at,
        'banner_title': BANNER_TITLE,
        'banner_body': BANNER_BODY,
        'badge_label': BADGE_LABEL,
        'tip_reason': TIP_REASON,
        'tip_cta_title': TIP_CTA_TITLE,
        'tip_cta_sub': TIP_CTA_SUB,
        'reasons_heading': REASONS_HEADING,
        'reasons_lead': REASONS_LEAD,
        'auto_push_sent_notice': AUTO_PUSH_SENT_NOTICE,
    }


def collect_owner_fcm_tokens(vehicle_data: dict | None, user_data: dict | None) -> list[str]:
    """Vehicle fcmToken first, then users/{uid}.fcmToken (same as manual push)."""
    vehicle = vehicle_data if isinstance(vehicle_data, dict) else {}
    user = user_data if isinstance(user_data, dict) else {}
    tokens: list[str] = []
    seen: set[str] = set()
    for raw in (vehicle.get('fcmToken'), user.get('fcmToken')):
        if isinstance(raw, str) and raw.strip() and raw.strip() not in seen:
            seen.add(raw.strip())
            tokens.append(raw.strip())
    return tokens


def approximate_coordinates(lat: Any, lng: Any) -> tuple[float, float] | None:
    """Round to a coarse grid for privacy (city/area scale, not exact pin)."""
    try:
        la = float(lat)
        lo = float(lng)
    except (TypeError, ValueError):
        return None
    if not (-90.0 <= la <= 90.0 and -180.0 <= lo <= 180.0):
        return None
    return round(la, COORD_DECIMALS), round(lo, COORD_DECIMALS)


def format_place_label(
    lat: float | None,
    lng: float | None,
    place_label: Any = None,
) -> str:
    label = str(place_label or '').strip()
    if label:
        return label[:160]
    if lat is None or lng is None:
        return ''
    ns = 'N' if lat >= 0 else 'S'
    ew = 'E' if lng >= 0 else 'W'
    return f'Near {abs(lat):.3f}°{ns}, {abs(lng):.3f}°{ew}'


def build_sighting_push_body(
    *,
    place_label: str = '',
    photo_count: int = 0,
    scanned_at_display: str = '',
) -> str:
    if place_label:
        body = (
            f'Someone spotted your vehicle near {place_label} '
            'while Lost Mode is on.'
        )
    else:
        body = AUTO_PUSH_BODY
    if scanned_at_display:
        body += f' Scanned at {scanned_at_display}.'
    if photo_count > 0:
        body += (
            f' {int(photo_count)} photo(s) attached — '
            'open the app notification for details.'
        )
    return body


def format_scanned_at_ist(when: datetime | None = None) -> str:
    """Human-readable scan time in India Standard Time for owner push copy."""
    try:
        import pytz

        tz = pytz.timezone('Asia/Kolkata')
    except Exception:
        tz = timezone.utc
    now = when or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    local = now.astimezone(tz)
    return local.strftime('%d %b %Y, %I:%M %p IST')


def parse_sighting_location(payload: dict | None) -> dict:
    """Extract approximate lat/lng + optional human place label from client JSON."""
    data = payload if isinstance(payload, dict) else {}
    coords = approximate_coordinates(data.get('latitude'), data.get('longitude'))
    lat = coords[0] if coords else None
    lng = coords[1] if coords else None
    accuracy = None
    try:
        if data.get('accuracy') is not None:
            accuracy = max(0.0, float(data.get('accuracy')))
    except (TypeError, ValueError):
        accuracy = None
    label = format_place_label(lat, lng, data.get('place_label') or data.get('placeLabel'))
    return {
        'latitude': lat,
        'longitude': lng,
        'accuracy_m': accuracy,
        'place_label': label,
        'has_location': lat is not None and lng is not None,
    }


def _decode_photo_data_url(raw: Any) -> tuple[bytes, str] | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    s = raw.strip()
    m = _DATA_URL_RE.match(s)
    if m:
        mime = m.group(1).lower().replace('image/jpg', 'image/jpeg')
        try:
            blob = base64.b64decode(m.group(2), validate=False)
        except Exception:
            return None
    else:
        # Raw base64 JPEG fallback
        try:
            blob = base64.b64decode(s, validate=False)
        except Exception:
            return None
        mime = 'image/jpeg'
    if not blob or len(blob) > MAX_PHOTO_BYTES:
        return None
    return blob, mime


def upload_sighting_photos(
    photos_raw: Any,
    *,
    vehicle_id: str,
    sighting_id: str,
    uploader: Any = None,
) -> list[str]:
    """Upload up to MAX_SIGHTING_PHOTOS images to Cloudinary; skip failures."""
    if uploader is None:
        import cloudinary.uploader as uploader  # type: ignore

    urls: list[str] = []
    if not isinstance(photos_raw, list):
        return urls
    vid = str(vehicle_id or 'unknown').strip() or 'unknown'
    sid = str(sighting_id or uuid.uuid4().hex).strip()
    for i, raw in enumerate(photos_raw[:MAX_SIGHTING_PHOTOS]):
        decoded = _decode_photo_data_url(raw)
        if not decoded:
            continue
        blob, mime = decoded
        try:
            result = uploader.upload(
                f'data:{mime};base64,{base64.b64encode(blob).decode("ascii")}',
                folder=f'lost_mode_sightings/{vid}',
                public_id=f'{sid}_{i}',
                overwrite=True,
                resource_type='image',
                transformation=[{'width': 1280, 'crop': 'limit', 'quality': 'auto:good'}],
            )
            url = (result or {}).get('secure_url') or (result or {}).get('url')
            if url:
                urls.append(str(url))
        except Exception as exc:
            logger.warning('Lost Mode photo upload failed: %s', exc)
    return urls


def store_lost_mode_sighting(
    db,
    *,
    owner_id: str,
    vehicle_id: str,
    qr_id: str,
    location: dict,
    photo_urls: list[str],
    source: str = 'web_qr',
    scanned_at: datetime | None = None,
    scanned_at_display: str = '',
) -> str:
    """Persist a sighting document; returns sighting id."""
    ref = db.collection('lostModeSightings').document()
    now = scanned_at or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    display = scanned_at_display or format_scanned_at_ist(now)
    doc = {
        'ownerId': str(owner_id or '').strip(),
        'vehicleId': str(vehicle_id or '').strip(),
        'qrId': str(qr_id or '').strip(),
        'source': source,
        'latitude': location.get('latitude'),
        'longitude': location.get('longitude'),
        'accuracyM': location.get('accuracy_m'),
        'placeLabel': location.get('place_label') or '',
        'photoUrls': list(photo_urls or []),
        'photoCount': len(photo_urls or []),
        'scannedAt': now,
        'scannedAtIso': now.isoformat(),
        'scannedAtDisplay': display,
        'createdAt': now,
        'createdAtIso': now.isoformat(),
    }
    ref.set(doc)
    return ref.id


def attempt_lost_mode_auto_push(
    *,
    request,
    db,
    qr_id: str,
    vehicle_id: str,
    vehicle_data: dict | None,
    user_data: dict | None,
    user_ref,
    vehicle_ref,
    push_capable: bool,
    send_push_fn: Callable[..., dict],
    location_payload: dict | None = None,
    photos_raw: Any = None,
    upload_photos: bool = True,
) -> dict:
    """
    Push the owner for a Lost Mode sighting on each QR scan.

    A short per-QR cooldown blocks only accidental double page-loads; every
    new scan (after the cooldown) notifies again with location + scan time.
    """
    from .scanner_notify_session_controls import (
        has_lost_mode_auto_push_sent,
        mark_lost_mode_auto_push_sent,
    )

    result = {
        'attempted': False,
        'sent': False,
        'skipped_reason': None,
        'notice': '',
        'sighting_id': None,
        'place_label': '',
        'photo_count': 0,
        'photo_urls': [],
    }
    lost = parse_vehicle_lost_mode(vehicle_data)
    if not lost['is_lost_mode']:
        result['skipped_reason'] = 'not_lost_mode'
        return result

    if has_lost_mode_auto_push_sent(request, qr_id):
        result['skipped_reason'] = 'already_sent'
        result['notice'] = AUTO_PUSH_SENT_NOTICE
        return result

    if not push_capable:
        result['skipped_reason'] = 'push_unavailable'
        return result

    tokens = collect_owner_fcm_tokens(vehicle_data, user_data)
    if not tokens:
        result['skipped_reason'] = 'no_token'
        return result

    owner_id = str((vehicle_data or {}).get('ownerId') or '')
    if not owner_id:
        result['skipped_reason'] = 'no_owner'
        return result

    location = parse_sighting_location(location_payload)
    scanned_at = datetime.now(timezone.utc)
    raw_scanned = None
    if isinstance(location_payload, dict):
        raw_scanned = location_payload.get('scanned_at') or location_payload.get(
            'scannedAt'
        )
    if isinstance(raw_scanned, str) and raw_scanned.strip():
        try:
            parsed = datetime.fromisoformat(
                raw_scanned.strip().replace('Z', '+00:00')
            )
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            scanned_at = parsed.astimezone(timezone.utc)
        except ValueError:
            pass
    scanned_at_display = format_scanned_at_ist(scanned_at)

    sighting_id = uuid.uuid4().hex[:16]
    photo_urls: list[str] = []
    if upload_photos and photos_raw:
        photo_urls = upload_sighting_photos(
            photos_raw,
            vehicle_id=vehicle_id,
            sighting_id=sighting_id,
        )

    try:
        sighting_id = store_lost_mode_sighting(
            db,
            owner_id=owner_id,
            vehicle_id=vehicle_id,
            qr_id=qr_id,
            location=location,
            photo_urls=photo_urls,
            scanned_at=scanned_at,
            scanned_at_display=scanned_at_display,
        )
    except Exception as exc:
        logger.warning('Lost Mode sighting store failed: %s', exc)
        sighting_id = sighting_id or uuid.uuid4().hex[:16]

    place = location.get('place_label') or ''
    body = build_sighting_push_body(
        place_label=place,
        photo_count=len(photo_urls),
        scanned_at_display=scanned_at_display,
    )
    result['attempted'] = True
    result['place_label'] = place
    result['photo_count'] = len(photo_urls)
    result['photo_urls'] = photo_urls
    result['sighting_id'] = sighting_id
    result['scanned_at'] = scanned_at.isoformat()
    result['scanned_at_display'] = scanned_at_display

    fcm_data = {
        'vehicleId': str(vehicle_id or ''),
        'qrId': str(qr_id or ''),
        'notificationType': 'vehicle_alert',
        'type': 'vehicle_alert',
        'lostMode': 'true',
        'lostModeSighting': 'true',
        'sightingId': str(sighting_id),
        'placeLabel': place,
        'photoCount': str(len(photo_urls)),
        'scannedAt': scanned_at.isoformat(),
        'scannedAtDisplay': scanned_at_display,
    }
    if location.get('has_location'):
        fcm_data['latitude'] = str(location['latitude'])
        fcm_data['longitude'] = str(location['longitude'])
        fcm_data['mapsUrl'] = (
            f"https://maps.google.com/?q={location['latitude']},{location['longitude']}"
        )
    if photo_urls:
        fcm_data['photoUrl'] = photo_urls[0]
        # Keep payload small — full list lives on the Firestore sighting doc.
        fcm_data['photoUrls'] = ','.join(photo_urls[:MAX_SIGHTING_PHOTOS])

    try:
        push_result = send_push_fn(
            db,
            user_id=owner_id,
            tokens=tokens,
            title=AUTO_PUSH_TITLE,
            body=body,
            data=fcm_data,
            store_inbox=True,
        )
    except Exception as exc:
        result['skipped_reason'] = 'send_failed'
        result['error'] = str(exc)
        return result

    success_count = int(push_result.get('success_count') or 0)
    failed_tokens = push_result.get('failed_tokens') or []
    vehicle_token = ''
    single_token = ''
    if isinstance(vehicle_data, dict):
        vehicle_token = vehicle_data.get('fcmToken') or ''
    if isinstance(user_data, dict):
        single_token = user_data.get('fcmToken') or ''

    if failed_tokens:
        try:
            if single_token and single_token in failed_tokens and user_ref is not None:
                user_ref.update({'fcmToken': ''})
        except Exception:
            pass
        try:
            if vehicle_token and vehicle_token in failed_tokens and vehicle_ref is not None:
                vehicle_ref.update({'fcmToken': ''})
        except Exception:
            pass

    if success_count > 0:
        mark_lost_mode_auto_push_sent(request, qr_id)
        result['sent'] = True
        time_bit = f' Scanned at {scanned_at_display}.' if scanned_at_display else ''
        if place and photo_urls:
            result['notice'] = (
                f'Owner notified with your approximate location ({place}) '
                f'and {len(photo_urls)} photo(s).{time_bit}'
            )
        elif place:
            result['notice'] = (
                f'Owner notified with your approximate location ({place}).{time_bit}'
            )
        elif photo_urls:
            result['notice'] = (
                f'Owner notified with {len(photo_urls)} photo(s).{time_bit}'
            )
        else:
            result['notice'] = AUTO_PUSH_SENT_NOTICE + time_bit
        result['fcm_message_id'] = push_result.get('message_id')
        return result

    result['skipped_reason'] = 'send_failed'
    result['error'] = str(push_result.get('last_error') or push_result.get('error') or 'Unknown')
    return result
