"""Shared constants for call routing (DID + PBX webhook)."""

# Public DID the PBX sends on webhook; also shown in send-notification tel: link context.
CALL_ROUTING_EXPECTED_DID = '8049649451'

# Pending intent row expires after this many seconds (see CallRouteIntent).
CALL_ROUTE_INTENT_TTL_SEC = 300

CALL_ROUTE_INVALID_FROM = 'Enter a valid mobile number.'
