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

AUTO_PUSH_TITLE = 'DANGER WARNING'
SPOTTER_LOCATION_TITLE = '📍 Spotter Location Received'
SPOTTER_LIVE_LOCATION_TITLE = '📍 Spotter live location update'
AUTO_PUSH_BODY = (
    'Your vehicle has been found. Please check the details immediately.'
)
AUTO_PUSH_SENT_NOTICE = (
    'Owner notified automatically on their phone — thank you for helping.'
)

MAX_SIGHTING_PHOTOS = 3
MAX_PHOTO_BYTES = 450_000
# ~110 m grid — prefer approximate area over exact pin (privacy).
COORD_DECIMALS = 3
# Maps pin / notification display precision (~0.1 m).
MAPS_COORD_DECIMALS = 6

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


def maps_coordinates(lat: Any, lng: Any) -> tuple[float, float] | None:
    """Validate and round lat/lng for Google Maps pins (6 decimal places)."""
    try:
        la = float(lat)
        lo = float(lng)
    except (TypeError, ValueError):
        return None
    if not (-90.0 <= la <= 90.0 and -180.0 <= lo <= 180.0):
        return None
    return round(la, MAPS_COORD_DECIMALS), round(lo, MAPS_COORD_DECIMALS)


def format_coord(value: float) -> str:
    """Stable decimal string for notification / URL (trim trailing zeros)."""
    return f'{float(value):.{MAPS_COORD_DECIMALS}f}'.rstrip('0').rstrip('.')


def google_maps_url(lat: float, lng: float) -> str:
    """Clickable Google Maps URL: https://www.google.com/maps?q=<lat>,<lng>."""
    return f'https://www.google.com/maps?q={format_coord(lat)},{format_coord(lng)}'


def build_lost_mode_sms_message(
    *,
    reason: str = '',
    latitude: Any = None,
    longitude: Any = None,
    max_len: int = 200,
) -> str:
    """
    MSG91 campaign ``var`` text (max ~200 chars).

    When coords are present, append a Google Maps link so owners without
    FCM can open the spotter location from SMS alone.
    """
    base = (reason or '').strip() or TIP_REASON
    coords = maps_coordinates(latitude, longitude)
    if not coords:
        return base[:max_len]
    url = google_maps_url(coords[0], coords[1])
    combined = f'{base} {url}'
    if len(combined) <= max_len:
        return combined
    room = max_len - len(url) - 1
    if room < 8:
        return url[:max_len]
    return f'{base[:room].rstrip()} {url}'


def build_spotter_location_notification(
    *,
    latitude: float,
    longitude: float,
    maps_url: str = '',
    shared_at_display: str = '',
    live_update: bool = False,
) -> tuple[str, str]:
    """
    Title + body for a location-share Lost Mode tip.

    Includes a clickable Google Maps URL and share/update timestamp.
    Lat/lng also go in FCM data fields for the app.
    """
    url = (maps_url or '').strip() or google_maps_url(latitude, longitude)
    if live_update:
        lines = [
            'A person updated their shared location while reporting your vehicle.',
            '',
            'View on Google Maps:',
            url,
        ]
        if shared_at_display:
            lines.extend(['', f'Updated at: {shared_at_display}'])
        return SPOTTER_LIVE_LOCATION_TITLE, '\n'.join(lines)

    lines = [
        'A person has shared their location while reporting your vehicle.',
        '',
        'View on Google Maps:',
        url,
    ]
    if shared_at_display:
        lines.extend(['', f'Shared at: {shared_at_display}'])
    return SPOTTER_LOCATION_TITLE, '\n'.join(lines)


def build_sighting_push_body(
    *,
    place_label: str = '',
    photo_count: int = 0,
    scanned_at_display: str = '',
    maps_url: str = '',
    latitude: Any = None,
    longitude: Any = None,
) -> str:
    coords = maps_coordinates(latitude, longitude)
    maps = (maps_url or '').strip()
    if coords:
        if not maps:
            maps = google_maps_url(coords[0], coords[1])
        _title, body = build_spotter_location_notification(
            latitude=coords[0],
            longitude=coords[1],
            maps_url=maps,
            shared_at_display=scanned_at_display,
        )
        if photo_count > 0:
            body += (
                f'\n\n{int(photo_count)} photo(s) attached — '
                'open the app notification for details.'
            )
        return body
    if maps:
        body = f'Your vehicle has been found. Live location: {maps}'
        if place_label:
            body = f'Your vehicle has been found near {place_label}. Map: {maps}'
    elif place_label:
        body = (
            f'Your vehicle has been found near {place_label}. '
            'Please check the details immediately.'
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
    """Extract lat/lng (maps precision) + optional human place label from client JSON."""
    data = payload if isinstance(payload, dict) else {}
    coords = maps_coordinates(data.get('latitude'), data.get('longitude'))
    lat = coords[0] if coords else None
    lng = coords[1] if coords else None
    accuracy = None
    try:
        if data.get('accuracy') is not None:
            accuracy = max(0.0, float(data.get('accuracy')))
    except (TypeError, ValueError):
        accuracy = None
    label = format_place_label(lat, lng, data.get('place_label') or data.get('placeLabel'))
    maps_url = ''
    if lat is not None and lng is not None:
        maps_url = google_maps_url(lat, lng)
    return {
        'latitude': lat,
        'longitude': lng,
        'accuracy_m': accuracy,
        'place_label': label,
        'google_maps_url': maps_url,
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
    had_location = bool(
        location
        and location.get('has_location')
        and location.get('latitude') is not None
        and location.get('longitude') is not None
    )
    maps_url = ''
    lat = None
    lng = None
    if had_location:
        lat = location.get('latitude')
        lng = location.get('longitude')
        maps_url = (
            (location.get('google_maps_url') or '').strip()
            or google_maps_url(float(lat), float(lng))
        )
    doc = {
        'ownerId': str(owner_id or '').strip(),
        'vehicleId': str(vehicle_id or '').strip(),
        'qrId': str(qr_id or '').strip(),
        'source': source,
        # Dedicated maps field so clients/inbox never drop the clickable URL.
        'googleMapsUrl': maps_url or None,
        'latitude': lat,
        'longitude': lng,
        'accuracyM': location.get('accuracy_m') if had_location else None,
        'placeLabel': (location.get('place_label') or '') if had_location else '',
        'locationShared': had_location,
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
    live_update: bool = False,
) -> dict:
    """
    Push the owner for a Lost Mode sighting on each QR page load (every scan).

    No cooldown — each successful page open notifies again. Approximate
    location may be empty on the initial server tip; scan time is always set.
    """
    result = {
        'attempted': False,
        'sent': False,
        'skipped_reason': None,
        'notice': '',
        'sighting_id': None,
        'place_label': '',
        'maps_url': '',
        'google_maps_url': '',
        'latitude': None,
        'longitude': None,
        'photo_count': 0,
        'photo_urls': [],
    }
    lost = parse_vehicle_lost_mode(vehicle_data)
    if not lost['is_lost_mode']:
        result['skipped_reason'] = 'not_lost_mode'
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
    maps_link = ''
    lat = location.get('latitude')
    lng = location.get('longitude')
    has_location = bool(location.get('has_location') and lat is not None and lng is not None)
    if has_location:
        maps_link = (
            (location.get('google_maps_url') or '').strip()
            or google_maps_url(float(lat), float(lng))
        )
    body = build_sighting_push_body(
        place_label=place,
        photo_count=len(photo_urls),
        scanned_at_display=scanned_at_display,
        maps_url=maps_link,
        latitude=lat,
        longitude=lng,
    )
    push_title = AUTO_PUSH_TITLE
    if has_location:
        push_title, body = build_spotter_location_notification(
            latitude=float(lat),
            longitude=float(lng),
            maps_url=maps_link,
            shared_at_display=scanned_at_display,
            live_update=bool(live_update),
        )
        if photo_urls and not live_update:
            body += (
                f'\n\n{len(photo_urls)} photo(s) attached — '
                'open the app notification for details.'
            )
    result['attempted'] = True
    result['place_label'] = place
    result['maps_url'] = maps_link
    result['google_maps_url'] = maps_link
    result['latitude'] = lat
    result['longitude'] = lng
    result['photo_count'] = len(photo_urls)
    result['photo_urls'] = photo_urls
    result['sighting_id'] = sighting_id
    result['scanned_at'] = scanned_at.isoformat()
    result['scanned_at_display'] = scanned_at_display
    # Shared tip body for SMS when push is unavailable.
    result['tip_body'] = body
    result['push_title'] = push_title

    tokens = collect_owner_fcm_tokens(vehicle_data, user_data)
    if not push_capable:
        result['skipped_reason'] = 'push_unavailable'
        return result
    if not tokens:
        result['skipped_reason'] = 'no_token'
        return result

    # Match mobile LostModeSightingService so the app opens DANGER WARNING + alarm.
    plate = ''
    vehicle_name = ''
    if isinstance(vehicle_data, dict):
        plate = str(
            vehicle_data.get('registrationNumber')
            or vehicle_data.get('registration_number')
            or vehicle_data.get('vehicleNumber')
            or ''
        ).strip()
        vehicle_name = str(
            vehicle_data.get('vehicleName')
            or vehicle_data.get('vehicle_name')
            or vehicle_data.get('name')
            or ''
        ).strip()

    fcm_data = {
        # Canonical mobile contract
        'type': 'lost_mode_sighting',
        'notificationType': 'lost_mode_sighting',
        'lost_mode': 'true',
        'urgent': 'true',
        'vehicle_id': str(vehicle_id or ''),
        'registration_number': plate,
        'vehicle_name': vehicle_name,
        'sighting_time': scanned_at.isoformat(),
        'scanned_at': scanned_at.isoformat(),
        'approx_location': place,
        'title': push_title,
        'body': body,
        # Legacy / web aliases (kept for older clients)
        'vehicleId': str(vehicle_id or ''),
        'qrId': str(qr_id or ''),
        'lostMode': 'true',
        'lostModeSighting': 'true',
        'sightingId': str(sighting_id),
        'placeLabel': place,
        'photoCount': str(len(photo_urls)),
        'scannedAt': scanned_at.isoformat(),
        'scannedAtDisplay': scanned_at_display,
        'registrationNumber': plate,
        'vehicleName': vehicle_name,
        'locationShared': 'true' if has_location else 'false',
        'liveUpdate': 'true' if live_update else 'false',
        'live_update': 'true' if live_update else 'false',
    }
    if has_location:
        lat_s = format_coord(float(lat))
        lng_s = format_coord(float(lng))
        # Dedicated + alias fields so URL is not stripped by clients/services.
        fcm_data['latitude'] = lat_s
        fcm_data['longitude'] = lng_s
        fcm_data['googleMapsUrl'] = maps_link
        fcm_data['google_maps_url'] = maps_link
        fcm_data['mapsUrl'] = maps_link
        fcm_data['maps_url'] = maps_link
        fcm_data['live_location_url'] = maps_link
        fcm_data['sharedAt'] = scanned_at.isoformat()
        fcm_data['sharedAtDisplay'] = scanned_at_display
        fcm_data['spotter_location_shared'] = 'true'
        if live_update:
            fcm_data['spotter_live_location'] = 'true'
    if photo_urls:
        fcm_data['photoUrl'] = photo_urls[0]
        # Keep payload small — full list lives on the Firestore sighting doc.
        fcm_data['photoUrls'] = ','.join(photo_urls[:MAX_SIGHTING_PHOTOS])

    try:
        push_result = send_push_fn(
            db,
            user_id=owner_id,
            tokens=tokens,
            title=push_title,
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
        result['sent'] = True
        time_bit = f' Scanned at {scanned_at_display}.' if scanned_at_display else ''
        if has_location:
            result['notice'] = (
                'Owner notified with your Google Maps location link.'
                f'{time_bit}'
            )
        elif place and photo_urls:
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
