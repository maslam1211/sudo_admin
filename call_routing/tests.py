"""Voice-bridge register/webhook tests for the company-number calling flow."""

import json
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from admin_app.models import CallRouteIntent
from call_routing.constants import (
    CALL_ROUTE_COMPANY_NUMBER_MISSING,
    CALL_ROUTE_INVALID_FROM,
    CALL_ROUTING_EXPECTED_DID,
)

COMPANY = '7907965255'
OWNER = '9876543210'
FINDER = '9000000001'


def _post(client, url, payload, **extra):
    return client.post(
        url,
        data=json.dumps(payload),
        content_type='application/json',
        **extra,
    )


@override_settings(COMPANY_PHONE_NUMBER=COMPANY, CALL_ROUTING_API_KEY='test-key')
class CompanyNumberCallFlowTests(TestCase):
    def setUp(self):
        self.register_url = reverse('register_call_destination')
        self.webhook_url = reverse('api_call_webhook')

    def _webhook(self, caller, did=CALL_ROUTING_EXPECTED_DID):
        return _post(
            self.client,
            self.webhook_url,
            {'from': caller, 'did': did},
            HTTP_AUTHORIZATION='Bearer test-key',
        )

    @patch('admin_app.scanner_contact_prefs.send_scanner_voice_call_attempt_push')
    @patch('admin_app.scanner_contact_prefs.validate_scanner_call_for_qr', return_value=None)
    def test_register_without_from_stores_company_number(self, _validate, push):
        response = _post(
            self.client,
            self.register_url,
            {'destination': OWNER, 'qr_id': 'qr-1'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'ok')
        self.assertNotIn(COMPANY, response.content.decode())
        intent = CallRouteIntent.objects.get()
        self.assertEqual(intent.caller_key, COMPANY)
        self.assertEqual(intent.destination, OWNER)
        push.assert_called_once()
        self.assertEqual(push.call_args.args[3], COMPANY)

    @patch('admin_app.scanner_contact_prefs.send_scanner_voice_call_attempt_push')
    @patch('admin_app.scanner_contact_prefs.validate_scanner_call_for_qr', return_value=None)
    def test_explicit_from_still_registers_that_caller(self, _validate, _push):
        response = _post(
            self.client,
            self.register_url,
            {'from': FINDER, 'destination': OWNER, 'qr_id': 'qr-1'},
        )
        self.assertEqual(response.status_code, 200)
        intent = CallRouteIntent.objects.get()
        self.assertEqual(intent.caller_key, FINDER)

    @patch('admin_app.scanner_contact_prefs.send_scanner_voice_call_attempt_push')
    @patch('admin_app.scanner_contact_prefs.validate_scanner_call_for_qr', return_value=None)
    def test_invalid_explicit_from_is_rejected(self, _validate, _push):
        response = _post(
            self.client,
            self.register_url,
            {'from': '123', 'destination': OWNER},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error'], CALL_ROUTE_INVALID_FROM)
        self.assertFalse(CallRouteIntent.objects.exists())

    @override_settings(COMPANY_PHONE_NUMBER='')
    def test_missing_company_number(self):
        response = _post(self.client, self.register_url, {'destination': OWNER})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()['error'], CALL_ROUTE_COMPANY_NUMBER_MISSING)
        self.assertFalse(CallRouteIntent.objects.exists())

    @override_settings(COMPANY_PHONE_NUMBER='12')
    def test_invalid_company_number(self):
        response = _post(self.client, self.register_url, {'destination': OWNER})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()['error'], CALL_ROUTE_COMPANY_NUMBER_MISSING)

    @patch(
        'admin_app.scanner_contact_prefs.validate_scanner_call_for_qr',
        return_value='Voice calling is paused for this vehicle.',
    )
    def test_provider_policy_failure(self, _validate):
        response = _post(
            self.client,
            self.register_url,
            {'destination': OWNER, 'qr_id': 'qr-1'},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error'], 'Voice calling is paused for this vehicle.')
        self.assertFalse(CallRouteIntent.objects.exists())

    def test_webhook_uses_company_intent_for_handset_cli(self):
        CallRouteIntent.objects.create(caller_key=COMPANY, destination=OWNER)
        response = self._webhook(FINDER)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['destination'], OWNER)
        self.assertNotIn(COMPANY, response.content.decode())

    def test_webhook_prefers_explicit_caller_over_company_intent(self):
        CallRouteIntent.objects.create(caller_key=FINDER, destination=OWNER)
        CallRouteIntent.objects.create(caller_key=COMPANY, destination='9111111111')
        response = self._webhook(FINDER)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['destination'], OWNER)

    def test_webhook_miss_when_company_number_unset(self):
        with self.settings(COMPANY_PHONE_NUMBER=''):
            response = self._webhook(FINDER)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error'], 'No destination')

    def test_expired_company_intent_is_not_used(self):
        intent = CallRouteIntent.objects.create(caller_key=COMPANY, destination=OWNER)
        CallRouteIntent.objects.filter(pk=intent.pk).update(
            created_at=timezone.now() - timedelta(seconds=301)
        )
        response = self._webhook(FINDER)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error'], 'No destination')
        self.assertFalse(CallRouteIntent.objects.filter(pk=COMPANY).exists())


class NotifyCallTemplateTests(TestCase):
    def test_voice_request_does_not_send_mobile_number(self):
        template = Path(__file__).resolve().parents[1] / 'admin_app' / 'templates' / 'send_notification.html'
        text = template.read_text()
        self.assertNotIn('from: fromDigits', text)
        self.assertNotIn('Enter your mobile number', text)
        self.assertIn('if (callPrepareBtn) callPrepareBtn.click();', text)
        self.assertIn('#callerPhoneInput', text)
        self.assertIn('display: none !important', text)
        start = text.index('fetch(callRegisterUrl,')
        snippet = text[start:start + 500]
        self.assertIn('destination: destDigits', snippet)
        self.assertNotIn('from:', snippet)
