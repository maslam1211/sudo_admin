"""Scanner notify page — voice-call abuse throttle and one-shot sheet completion."""

from __future__ import annotations

import math
import time

from django.http import JsonResponse

# -----------------------------------------------------------------------------
# Notify sheet: after successful SMS/push/call-register, sheet is consumed once.
# -----------------------------------------------------------------------------

SHEET_DONE_KEY = "sudo_notify_sheet_done_{qr_id}"


def notify_sheet_session_key(qr_id: str) -> str:
    return SHEET_DONE_KEY.format(qr_id=str(qr_id or "").strip())


def mark_notify_sheet_done(request, qr_id: str) -> None:
    request.session[notify_sheet_session_key(qr_id)] = True
    request.session.modified = True


def is_notify_sheet_done(request, qr_id: str) -> bool:
    return bool(request.session.get(notify_sheet_session_key(qr_id)))


def pop_notify_sheet_done_for_terminal_view(request, qr_id: str) -> bool:
    """Return True once if the next full page load should show the terminal sheet."""
    key = notify_sheet_session_key(qr_id)
    if request.session.get(key):
        request.session.pop(key, None)
        request.session.modified = True
        return True
    return False


# -----------------------------------------------------------------------------
# Voice: per (qr_id, caller) —
#   • First segment: 2 successful bridge regs, then 2 min cooldown.
#   • After that cooldown: only 1 success per window; further abuse → 5 min cooldown.
#   • No voice activity for 24 h → full reset (smooth behaviour for returning users).
# -----------------------------------------------------------------------------

SESSION_VOICE_KEY = "notify_voice_throttle_pairs_v2"

MAX_VOICE_SUCCESSES_INITIAL = 2
VOICE_COOLDOWN_INITIAL_SEC = 120  # 2 minutes

MAX_VOICE_SUCCESSES_STRICT = 1
VOICE_COOLDOWN_STRICT_SEC = 300  # 5 minutes

VOICE_THROTTLE_IDLE_RESET_SEC = 24 * 3600


def _voice_pair_key(qr_id: str, caller_10: str) -> str:
    return f"{qr_id}:{caller_10}"


def _voice_pairs_bucket(request):
    bag = request.session.get(SESSION_VOICE_KEY)
    if not isinstance(bag, dict):
        bag = {}
    pairs = bag.get("pairs")
    if not isinstance(pairs, dict):
        pairs = {}
    bag["pairs"] = pairs
    request.session[SESSION_VOICE_KEY] = bag
    return pairs


def _default_voice_ent(now: float) -> dict:
    return {
        "success_count": 0,
        "cooldown_until": 0.0,
        "strict_mode": False,
        "last_activity_ts": now,
    }


def _freshen_voice_entry(ent: dict, now: float) -> None:
    """Expire idle state (24h), then expire cooldown windows and graduate into strict mode."""
    last = float(ent.get("last_activity_ts") or 0)
    if last > 0 and (now - last) >= VOICE_THROTTLE_IDLE_RESET_SEC:
        ent.clear()
        ent.update(_default_voice_ent(now))
        return

    cool = float(ent.get("cooldown_until") or 0)
    if cool and now >= cool:
        ent["cooldown_until"] = 0.0
        ent["success_count"] = 0
        # Finished first 2-call burst + 2 min wait → subsequent limits are 1 call per 5 min cooldown.
        if not ent.get("strict_mode"):
            ent["strict_mode"] = True


def _touch_voice_ent(ent: dict, now: float) -> None:
    ent["last_activity_ts"] = now


def _max_voice_successes_before_block(ent: dict) -> int:
    return MAX_VOICE_SUCCESSES_STRICT if ent.get("strict_mode") else MAX_VOICE_SUCCESSES_INITIAL


def _cooldown_sec_for_next_block(ent: dict) -> int:
    return (
        VOICE_COOLDOWN_STRICT_SEC if ent.get("strict_mode") else VOICE_COOLDOWN_INITIAL_SEC
    )


def _voice_cooldown_json(seconds: float) -> JsonResponse:
    s = max(1, int(math.ceil(seconds)))
    mins = max(1, int(math.ceil(s / 60)))
    return JsonResponse(
        {
            "status": "error",
            "error_type": "voice_call_cooldown",
            "message": (
                "You’ve reached the voice call limit for now. "
                f"Please wait about {mins} minute(s) before placing another voice call "
                "(SMS and push stay available)."
            ),
            "cooldown_seconds_remaining": s,
        },
        status=429,
    )


def voice_register_maybe_block(request, qr_id: str, caller_norm10: str) -> JsonResponse | None:
    """
    Called before registering a PBX dial for (qr_id, caller).
    Returns JsonResponse when the call must be blocked, else None.
    """
    qr_id = str(qr_id or "").strip()
    if len(caller_norm10) != 10:
        return None

    now = time.time()
    pairs = _voice_pairs_bucket(request)
    pk = _voice_pair_key(qr_id, caller_norm10)
    ent = pairs.get(pk)
    if not isinstance(ent, dict):
        ent = _default_voice_ent(now)
    _freshen_voice_entry(ent, now)
    _touch_voice_ent(ent, now)

    cool = float(ent.get("cooldown_until") or 0)
    if cool > now:
        pairs[pk] = ent
        request.session.modified = True
        return _voice_cooldown_json(cool - now)

    cap = _max_voice_successes_before_block(ent)
    cnt = int(ent.get("success_count") or 0)
    if cnt >= cap:
        cd_sec = _cooldown_sec_for_next_block(ent)
        ent["cooldown_until"] = now + cd_sec
        pairs[pk] = ent
        request.session.modified = True
        return _voice_cooldown_json(cd_sec)

    pairs[pk] = ent
    request.session.modified = True
    return None


def voice_register_record_success(request, qr_id: str, caller_norm10: str) -> None:
    """Increment successful voice registers after the bridge accepted the request."""
    qr_id = str(qr_id or "").strip()
    if len(caller_norm10) != 10:
        return
    now = time.time()
    pairs = _voice_pairs_bucket(request)
    pk = _voice_pair_key(qr_id, caller_norm10)
    ent = pairs.get(pk)
    if not isinstance(ent, dict):
        ent = _default_voice_ent(now)
    _freshen_voice_entry(ent, now)
    _touch_voice_ent(ent, now)
    ent["success_count"] = int(ent.get("success_count") or 0) + 1
    pairs[pk] = ent
    request.session.modified = True
