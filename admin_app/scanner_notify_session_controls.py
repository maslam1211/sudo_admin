"""Scanner notify page — messaging attempt limits and voice-call throttle."""

from __future__ import annotations

import math
import time

from django.http import JsonResponse

# -----------------------------------------------------------------------------
# Notify sheet / messaging attempts (SMS + push share one counter per QR):
#   1st & 2nd success → stay on Contact Owner
#   3rd success → mark sheet done (client redirects to landing)
# Voice call-register does not consume the sheet (user may cancel the dialer).
# -----------------------------------------------------------------------------

SHEET_DONE_KEY = "sudo_notify_sheet_done_{qr_id}"
MESSAGING_ATTEMPTS_KEY = "sudo_notify_msg_attempts_{qr_id}"
MAX_MESSAGING_ATTEMPTS_BEFORE_HOME = 3


def notify_sheet_session_key(qr_id: str) -> str:
    return SHEET_DONE_KEY.format(qr_id=str(qr_id or "").strip())


def notify_messaging_attempts_key(qr_id: str) -> str:
    return MESSAGING_ATTEMPTS_KEY.format(qr_id=str(qr_id or "").strip())


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


def clear_notify_messaging_attempts(request, qr_id: str) -> None:
    key = notify_messaging_attempts_key(qr_id)
    if key in request.session:
        request.session.pop(key, None)
        request.session.modified = True


def clear_notify_session_for_rescan(request, qr_id: str) -> None:
    """Full reset when the scanner reloads with ?_sudo_rescan=1."""
    clear_notify_sheet_done(request, qr_id)
    clear_notify_messaging_attempts(request, qr_id)


def pop_notify_sheet_done_for_terminal_view(request, qr_id: str) -> bool:
    """Return True once if the next full page load should show the terminal sheet."""
    key = notify_sheet_session_key(qr_id)
    if request.session.get(key):
        request.session.pop(key, None)
        request.session.modified = True
        return True
    return False


def record_notify_messaging_success(request, qr_id: str) -> dict:
    """
    Count a successful SMS/push for this QR session.

    Returns:
      attempt (1-based), redirect_home (True on 3rd+ success).
    On the 3rd success the notify sheet is marked done so a reload shows
    the terminal/landing path.
    """
    qr_id = str(qr_id or "").strip()
    key = notify_messaging_attempts_key(qr_id)
    attempt = int(request.session.get(key) or 0) + 1
    request.session[key] = attempt
    request.session.modified = True
    redirect_home = attempt >= MAX_MESSAGING_ATTEMPTS_BEFORE_HOME
    if redirect_home:
        mark_notify_sheet_done(request, qr_id)
    return {
        "attempt": attempt,
        "redirect_home": redirect_home,
        "max_before_home": MAX_MESSAGING_ATTEMPTS_BEFORE_HOME,
    }


# -----------------------------------------------------------------------------
# Voice: per (qr_id, caller) —
#   • 1st & 2nd successful bridge regs → free (no wait)
#   • After 3rd → 30s, 4th → 30s, 5th → 60s, 6th+ → 120s (capped)
#   • No voice activity for 24 h → full reset
# -----------------------------------------------------------------------------

SESSION_VOICE_KEY = "notify_voice_throttle_pairs_v4"

FREE_VOICE_ATTEMPTS = 2
VOICE_COOLDOWN_STEPS_SEC = (30, 30, 60, 120)

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
        # Keep success_count / cooldown_step so waits stay progressive.
        ent["cooldown_until"] = 0.0


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
    """Apply next progressive wait (30 → 30 → 60 → 120) and advance the step."""
    step = int(ent.get("cooldown_step") or 0)
    cd_sec = _cooldown_sec_for_step(step)
    ent["cooldown_until"] = now + cd_sec
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

    pairs[pk] = ent
    request.session.modified = True
    return None


def voice_register_record_success(request, qr_id: str, caller_norm10: str) -> int | None:
    """
    Increment successful voice registers after the bridge accepted the request.

    Returns cooldown seconds when this success starts a wait before the next
    dial (after the 3rd+ call); otherwise None.
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
    # 1st & 2nd calls are free; from the 3rd onward start progressive waits.
    if ent["success_count"] > FREE_VOICE_ATTEMPTS:
        started_cd = _start_voice_cooldown(ent, now)

    pairs[pk] = ent
    request.session.modified = True
    return started_cd
