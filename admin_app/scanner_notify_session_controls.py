"""Scanner notify page — timed session, messaging attempts, and voice-call throttle."""

from __future__ import annotations

import math
import time

from django.http import JsonResponse


# -----------------------------------------------------------------------------
# Notify session (SMS / push / call share one window per QR):
#   • Stay on Contact Owner after send/call (no instant landing redirect)
#   • Client inactivity timeout → calm wrap-up → landing page
#   • Server TTL is a visit ceiling (refreshed on success) for QR continuity
#   • ?_sudo_rescan=1 clears the session for a fresh start
# -----------------------------------------------------------------------------

SHEET_DONE_KEY = "sudo_notify_sheet_done_{qr_id}"
MESSAGING_ATTEMPTS_KEY = "sudo_notify_msg_attempts_{qr_id}"
SESSION_UNTIL_KEY = "sudo_notify_session_until_{qr_id}"
LOST_AUTO_PUSH_KEY = "sudo_lost_auto_push_{qr_id}"

# Hard ceiling for the server-side visit (QR continuity after a successful contact).
NOTIFY_SESSION_TTL_SEC = 180
# Client inactivity → landing redirect (seconds without interaction on Contact Owner).
NOTIFY_IDLE_TIMEOUT_SEC = 60


def notify_sheet_session_key(qr_id: str) -> str:
    return SHEET_DONE_KEY.format(qr_id=str(qr_id or "").strip())


def notify_messaging_attempts_key(qr_id: str) -> str:
    return MESSAGING_ATTEMPTS_KEY.format(qr_id=str(qr_id or "").strip())


def notify_session_until_key(qr_id: str) -> str:
    return SESSION_UNTIL_KEY.format(qr_id=str(qr_id or "").strip())


def lost_mode_auto_push_key(qr_id: str) -> str:
    return LOST_AUTO_PUSH_KEY.format(qr_id=str(qr_id or "").strip())


def mark_notify_sheet_done(request, qr_id: str) -> None:
    """Legacy / explicit lock. Prefer touch + TTL expiry for the normal flow."""
    request.session[notify_sheet_session_key(qr_id)] = True
    request.session.modified = True


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


def clear_notify_session_until(request, qr_id: str) -> None:
    key = notify_session_until_key(qr_id)
    if key in request.session:
        request.session.pop(key, None)
        request.session.modified = True


def clear_lost_mode_auto_push(request, qr_id: str) -> None:
    """Allow another automatic Lost Mode sighting push after a fresh rescan."""
    key = lost_mode_auto_push_key(qr_id)
    if key in request.session:
        request.session.pop(key, None)
        request.session.modified = True


def has_lost_mode_auto_push_sent(request, qr_id: str) -> bool:
    return bool(request.session.get(lost_mode_auto_push_key(qr_id)))


def mark_lost_mode_auto_push_sent(request, qr_id: str) -> None:
    request.session[lost_mode_auto_push_key(qr_id)] = True
    request.session.modified = True


def clear_notify_session_for_rescan(request, qr_id: str) -> None:
    """Full reset when the scanner reloads with ?_sudo_rescan=1."""
    clear_notify_sheet_done(request, qr_id)
    clear_notify_messaging_attempts(request, qr_id)
    clear_notify_session_until(request, qr_id)
    clear_lost_mode_auto_push(request, qr_id)


def get_notify_session_until(request, qr_id: str) -> float | None:
    raw = request.session.get(notify_session_until_key(qr_id))
    try:
        until = float(raw)
    except (TypeError, ValueError):
        return None
    if until <= 0:
        return None
    return until


def is_notify_session_active(request, qr_id: str) -> bool:
    until = get_notify_session_until(request, qr_id)
    if until is None:
        return False
    return time.time() < until


def is_notify_session_expired(request, qr_id: str) -> bool:
    """True when a session was started and its TTL has elapsed."""
    until = get_notify_session_until(request, qr_id)
    if until is None:
        return False
    return time.time() >= until


def touch_notify_active_session(request, qr_id: str) -> dict:
    """
    Start or refresh the Contact Owner session window after SMS / push / call.

    Always keeps the user on Contact Owner (redirect_home is False). Soft
    wrap-up / landing happens client-side after idle; this TTL is the ceiling.
    """
    qr_id = str(qr_id or "").strip()
    clear_notify_sheet_done(request, qr_id)
    until = time.time() + NOTIFY_SESSION_TTL_SEC
    request.session[notify_session_until_key(qr_id)] = until
    request.session.modified = True
    return {
        "session_expires_at": until,
        "session_ttl_sec": NOTIFY_SESSION_TTL_SEC,
        "redirect_home": False,
    }


def is_notify_sheet_done(request, qr_id: str) -> bool:
    """
    Block further notify / call-register actions until the user rescans.

    True when the timed session has expired, or a legacy explicit done flag is set.
    """
    if bool(request.session.get(notify_sheet_session_key(qr_id))):
        return True
    return is_notify_session_expired(request, qr_id)


def pop_notify_sheet_done_for_terminal_view(request, qr_id: str) -> bool:
    """
    Legacy helper: return True once if an explicit sheet-done flag was set.

    Prefer should_show_notify_terminal_on_load for new code.
    """
    key = notify_sheet_session_key(qr_id)
    if request.session.get(key):
        request.session.pop(key, None)
        request.session.modified = True
        return True
    return False


def should_show_notify_terminal_on_load(request, qr_id: str) -> bool:
    """
    Whether GET should show the calm wrap-up sheet.

    Active session → False (continue Contact Owner, including QR reload).
    Expired session → True once, then clear so a later scan starts fresh.
    Never started → False.
    """
    if is_notify_session_active(request, qr_id):
        return False
    if is_notify_session_expired(request, qr_id):
        # One-shot wrap-up: don't trap the scanner in an expired loop on every QR.
        clear_notify_session_until(request, qr_id)
        clear_notify_sheet_done(request, qr_id)
        return True
    # Legacy explicit done flag (one-shot pop so a later rescan works).
    return pop_notify_sheet_done_for_terminal_view(request, qr_id)


def record_notify_messaging_success(request, qr_id: str) -> dict:
    """
    Count a successful SMS/push for this QR session and refresh the visit window.

    Returns:
      attempt (1-based), redirect_home (always False), session_ttl_sec,
      session_expires_at.
    """
    qr_id = str(qr_id or "").strip()
    key = notify_messaging_attempts_key(qr_id)
    attempt = int(request.session.get(key) or 0) + 1
    request.session[key] = attempt
    request.session.modified = True
    session_meta = touch_notify_active_session(request, qr_id)
    return {
        "attempt": attempt,
        "redirect_home": False,
        "session_ttl_sec": session_meta["session_ttl_sec"],
        "session_expires_at": session_meta["session_expires_at"],
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
