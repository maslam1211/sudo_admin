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


def clear_notify_sheet_done(request, qr_id: str) -> None:
    """Allow a fresh scanner session after the user rescans the QR."""
    key = notify_sheet_session_key(qr_id)
    if key in request.session:
        request.session.pop(key, None)
        request.session.modified = True


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
#   • Up to 3 successful bridge regs, then a progressive wait:
#       1st block → 30s, 2nd → 60s, 3rd+ → 120s
#   • After each wait expires, another 3 calls are allowed.
#   • No voice activity for 24 h → full reset (smooth behaviour for returning users).
# -----------------------------------------------------------------------------

SESSION_VOICE_KEY = "notify_voice_throttle_pairs_v3"

MAX_VOICE_SUCCESSES_PER_WINDOW = 3
VOICE_COOLDOWN_STEPS_SEC = (30, 60, 120)

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
        "cooldown_step": 0,  # index into VOICE_COOLDOWN_STEPS_SEC
        "last_activity_ts": now,
    }


def _freshen_voice_entry(ent: dict, now: float) -> None:
    """Expire idle state (24h), then clear finished cooldown windows."""
    last = float(ent.get("last_activity_ts") or 0)
    if last > 0 and (now - last) >= VOICE_THROTTLE_IDLE_RESET_SEC:
        ent.clear()
        ent.update(_default_voice_ent(now))
        return

    cool = float(ent.get("cooldown_until") or 0)
    if cool and now >= cool:
        ent["cooldown_until"] = 0.0
        ent["success_count"] = 0


def _touch_voice_ent(ent: dict, now: float) -> None:
    ent["last_activity_ts"] = now


def _cooldown_sec_for_step(step: int) -> int:
    steps = VOICE_COOLDOWN_STEPS_SEC
    if not steps:
        return 30
    idx = max(0, min(int(step or 0), len(steps) - 1))
    return int(steps[idx])


def _format_cooldown_wait_message(seconds: int) -> str:
    s = max(1, int(seconds))
    if s < 60:
        return (
            "You’ve reached the voice call limit for now. "
            f"Please wait {s} second(s) before placing another voice call "
            "(SMS and push stay available)."
        )
    mins = max(1, int(math.ceil(s / 60)))
    return (
        "You’ve reached the voice call limit for now. "
        f"Please wait about {mins} minute(s) before placing another voice call "
        "(SMS and push stay available)."
    )


def _voice_cooldown_json(seconds: float) -> JsonResponse:
    s = max(1, int(math.ceil(seconds)))
    return JsonResponse(
        {
            "status": "error",
            "error_type": "voice_call_cooldown",
            "message": _format_cooldown_wait_message(s),
            "cooldown_seconds_remaining": s,
        },
        status=429,
    )


def _start_voice_cooldown(ent: dict, now: float) -> int:
    """Apply next progressive wait (30 → 60 → 120) and advance the step."""
    step = int(ent.get("cooldown_step") or 0)
    cd_sec = _cooldown_sec_for_step(step)
    ent["cooldown_until"] = now + cd_sec
    ent["success_count"] = 0
    ent["cooldown_step"] = min(step + 1, len(VOICE_COOLDOWN_STEPS_SEC) - 1)
    return cd_sec


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

    cnt = int(ent.get("success_count") or 0)
    if cnt >= MAX_VOICE_SUCCESSES_PER_WINDOW:
        cd_sec = _start_voice_cooldown(ent, now)
        pairs[pk] = ent
        request.session.modified = True
        return _voice_cooldown_json(cd_sec)

    pairs[pk] = ent
    request.session.modified = True
    return None


def voice_register_record_success(request, qr_id: str, caller_norm10: str) -> int | None:
    """
    Increment successful voice registers after the bridge accepted the request.

    Returns cooldown seconds when this success filled the 3-call window and a
    progressive wait (30 / 60 / 120) was started; otherwise None.
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
        # Should not happen if maybe_block ran first; keep cooldown intact.
        pairs[pk] = ent
        request.session.modified = True
        return max(1, int(math.ceil(cool - now)))

    ent["success_count"] = int(ent.get("success_count") or 0) + 1
    started_cd: int | None = None
    # If this success fills the window, start waiting immediately so the UI
    # shows 30 / 60 / 120 before the next dial attempt.
    if ent["success_count"] >= MAX_VOICE_SUCCESSES_PER_WINDOW:
        started_cd = _start_voice_cooldown(ent, now)

    pairs[pk] = ent
    request.session.modified = True
    return started_cd
