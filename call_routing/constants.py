"""Shared constants for PBX call-bridge (must match ``admin_app.views.DYNAMIC_CALL_DID``)."""

# Seconds to keep caller_key -> destination after register (webhook lookup).
CALL_ROUTE_INTENT_TTL_SEC = 300

# JSON error when ``from`` is not a valid 10-digit Indian mobile.
CALL_ROUTE_INVALID_FROM = 'Invalid mobile number'

# Inbound DID the carrier sends; register flow and webhook must match.
CALL_ROUTING_EXPECTED_DID = '8049649451'
