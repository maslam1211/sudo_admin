"""Shared constants for call routing (DID + PBX webhook)."""

# Inbound DID the carrier sends; register flow and webhook must match.
CALL_ROUTING_EXPECTED_DID = '8049649451'

# Pending intent row expires after this many seconds (see CallRouteIntent).
CALL_ROUTE_INTENT_TTL_SEC = 300

# JSON error when ``from`` is not a valid 10-digit Indian mobile.
CALL_ROUTE_INVALID_FROM = 'Enter a valid mobile number.'
