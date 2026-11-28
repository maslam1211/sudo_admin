"""Tests for the mobile API (api/). Firebase and MSG91 are replaced by fakes."""

from __future__ import annotations

import io
import json
import shutil
import tempfile
from unittest import mock

from django.core.management import call_command
from django.http import JsonResponse
from django.test import Client, TestCase, override_settings

from api.models import PrivateFile, RateLimitBucket
from api.tests.fakes import FakeAuth, FakeDB, FakeUser

JPEG = b'\xff\xd8\xff\xe0' + b'\x00' * 200
OWNER_PHONE = '9876543210'


def _verify(token):
    if token.startswith('good-'):
        uid = token[len('good-'):]
        return {'uid': uid, 'phone_number': ''}
    raise ValueError('bad token')


class ApiTestBase(TestCase):
    def setUp(self):
        self.db = FakeDB()
        self.auth = FakeAuth()
        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        patches = [
            mock.patch('api.firebase.verify_id_token', side_effect=_verify),
            mock.patch('api.firebase.firestore_db', return_value=self.db),
            mock.patch('api.firebase.auth_module', return_value=self.auth),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        settings_override = override_settings(
            PRIVATE_MEDIA_ROOT=self.media, API_REQUIRE_APP_CHECK=False,
            MSG91_AUTH_KEY='k', MSG91_OTP_TEMPLATE_ID='t',
        )
        settings_override.enable()
        self.addCleanup(settings_override.disable)
        self.client = Client()

    def post(self, path, body=None, uid=None, **extra):
        if uid:
            extra['HTTP_AUTHORIZATION'] = f'Bearer good-{uid}'
        return self.client.post(path, data=json.dumps(body or {}), content_type='application/json', **extra)

    def error_code(self, response):
        return response.json()['error']['code']

    def seed_vehicle(self, vehicle_id='veh1', owner='owner1', **vehicle):
        self.db.put(f'vehicles/{vehicle_id}', {'ownerId': owner, 'registrationNumber': 'KL07AB1234',
                                               'ownerContact': OWNER_PHONE, **vehicle})
        self.db.put(f'users/{owner}', {'contactNumber': OWNER_PHONE, 'liveStatus': 'available'})


# ─── Auth plumbing ────────────────────────────────────────────────────────────
class AuthTests(ApiTestBase):
    def test_health_is_public(self):
        self.assertEqual(self.client.get('/api/v1/health').json(), {'ok': True})

    def test_missing_or_bad_token_is_401_in_api_shape(self):
        for headers in ({}, {'HTTP_AUTHORIZATION': 'Bearer nope'}):
            r = self.client.post('/api/v1/vehicles/veh1/sms', data='{}', content_type='application/json', **headers)
            self.assertEqual(r.status_code, 401)
            self.assertEqual(self.error_code(r), 'unauthenticated')

    def test_validation_errors_use_api_shape(self):
        r = self.post('/api/v1/auth/otp/send', {})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(self.error_code(r), 'invalid-argument')

    @override_settings(API_REQUIRE_APP_CHECK=True)
    def test_app_check_required_when_enabled(self):
        r = self.post('/api/v1/auth/otp/send', {'phone': OWNER_PHONE})
        self.assertEqual(r.status_code, 401)
        with mock.patch('api.firebase.verify_app_check_token', return_value={}), \
                mock.patch('admin_app.msg91_otp.send_otp'):
            r = self.post('/api/v1/auth/otp/send', {'phone': OWNER_PHONE}, HTTP_X_FIREBASE_APPCHECK='tok')
        self.assertEqual(r.status_code, 200)

    def test_client_ip_ignores_forged_forwarded_for(self):
        from api.security import client_ip
        request = mock.Mock(META={'HTTP_X_FORWARDED_FOR': '6.6.6.6, 1.2.3.4', 'REMOTE_ADDR': '127.0.0.1'})
        self.assertEqual(client_ip(request), '1.2.3.4')


# ─── OTP ──────────────────────────────────────────────────────────────────────
class OtpTests(ApiTestBase):
    def test_send_normalises_number_and_calls_msg91(self):
        with mock.patch('admin_app.msg91_otp.send_otp') as send:
            r = self.post('/api/v1/auth/otp/send', {'phone': '+91 98765 43210'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {'sent': True})
        send.assert_called_once_with('+919876543210')

    def test_send_rejects_invalid_number(self):
        r = self.post('/api/v1/auth/otp/send', {'phone': '12345'})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.error_code(r), 'invalid-argument')

    def test_send_is_rate_limited_per_number(self):
        with mock.patch('admin_app.msg91_otp.send_otp') as send:
            codes = [self.post('/api/v1/auth/otp/send', {'phone': OWNER_PHONE}).status_code for _ in range(6)]
        self.assertEqual(codes, [200] * 5 + [429])
        self.assertEqual(send.call_count, 5)

    def test_msg91_failure_is_unavailable_not_500(self):
        from admin_app.msg91_otp import Msg91OtpError
        with mock.patch('admin_app.msg91_otp.send_otp', side_effect=Msg91OtpError('HTTP 500')):
            r = self.post('/api/v1/auth/otp/send', {'phone': OWNER_PHONE})
        self.assertEqual(r.status_code, 503)

    def test_resend_uses_retry_and_does_not_send_twice(self):
        ok = mock.Mock(status_code=200, json=lambda: {'type': 'success'})
        with mock.patch('api.routers.otp.requests.get', return_value=ok), \
                mock.patch('admin_app.msg91_otp.send_otp') as send:
            r = self.post('/api/v1/auth/otp/resend', {'phone': OWNER_PHONE})
        self.assertEqual(r.status_code, 200)
        send.assert_not_called()

    def test_resend_falls_back_to_fresh_send(self):
        refused = mock.Mock(status_code=200, json=lambda: {'type': 'error'})
        with mock.patch('api.routers.otp.requests.get', return_value=refused), \
                mock.patch('admin_app.msg91_otp.send_otp') as send:
            self.post('/api/v1/auth/otp/resend', {'phone': OWNER_PHONE})
        send.assert_called_once()

    def _login(self, otp='1234'):
        with mock.patch('admin_app.msg91_otp.verify_otp'):
            return self.post('/api/v1/auth/otp/verify', {'phone': OWNER_PHONE, 'otp': otp})

    def test_login_reuses_auth_user_with_this_phone(self):
        self.auth.users['u-phone'] = FakeUser('u-phone', '+919876543210')
        r = self._login()
        self.assertEqual(r.json(), {'customToken': 'token-for-u-phone'})
        self.assertEqual(self.auth.created, [])

    def test_login_links_existing_profile_instead_of_new_account(self):
        self.auth.users['u-google'] = FakeUser('u-google')
        self.db.put('users/u-google', {'contactNumber': OWNER_PHONE})
        r = self._login()
        self.assertEqual(r.json()['customToken'], 'token-for-u-google')
        self.assertEqual(self.auth.users['u-google'].phone_number, '+919876543210')
        self.assertEqual(self.auth.created, [])

    def test_login_recreates_missing_auth_record_under_profile_uid(self):
        self.db.put('users/u-orphan', {'contactNumber': OWNER_PHONE})
        r = self._login()
        self.assertEqual(r.json()['customToken'], 'token-for-u-orphan')
        self.assertEqual(self.auth.created, ['u-orphan'])

    def test_login_creates_new_user_for_unknown_number(self):
        r = self._login()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(self.auth.created), 1)

    def test_wrong_code_is_invalid_argument_with_msg91_message(self):
        from admin_app.msg91_otp import Msg91OtpError
        with mock.patch('admin_app.msg91_otp.verify_otp', side_effect=Msg91OtpError('OTP not match')):
            r = self.post('/api/v1/auth/otp/verify', {'phone': OWNER_PHONE, 'otp': '0000'})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()['error'], {'code': 'invalid-argument', 'message': 'OTP not match'})

    def test_verify_attempts_are_limited(self):
        from admin_app.msg91_otp import Msg91OtpError
        with mock.patch('admin_app.msg91_otp.verify_otp', side_effect=Msg91OtpError('bad')):
            codes = [self.post('/api/v1/auth/otp/verify', {'phone': OWNER_PHONE, 'otp': '0000'}).status_code
                     for _ in range(9)]
        self.assertEqual(codes[-1], 429)

    def test_phone_verify_needs_sign_in_and_does_not_issue_token(self):
        self.assertEqual(self.post('/api/v1/phone/otp/verify', {'phone': OWNER_PHONE, 'otp': '1234'}).status_code, 401)
        with mock.patch('admin_app.msg91_otp.verify_otp'):
            r = self.post('/api/v1/phone/otp/verify', {'phone': OWNER_PHONE, 'otp': '1234'}, uid='u1')
        self.assertEqual(r.json(), {'verified': True, 'phone': OWNER_PHONE})


# ─── Scanner SMS ──────────────────────────────────────────────────────────────
@mock.patch('api.routers.vehicle_contact.send_vehicle_issue_sms', return_value={'ok': True})
class ScannerSmsTests(ApiTestBase):
    def test_sends_to_owner_number_resolved_on_server(self, send):
        self.seed_vehicle()
        r = self.post('/api/v1/vehicles/veh1/sms', {'message': 'Your vehicle lights are on'}, uid='scanner')
        self.assertEqual(r.status_code, 200)
        send.assert_called_once_with(digits_10=OWNER_PHONE, message='Your vehicle lights are on')

    def test_unknown_vehicle_is_404(self, send):
        r = self.post('/api/v1/vehicles/missing/sms', {'message': 'hi'}, uid='scanner')
        self.assertEqual(r.status_code, 404)
        send.assert_not_called()

    def test_owner_on_do_not_disturb_is_refused(self, send):
        self.seed_vehicle()
        self.db.put('users/owner1', {'contactNumber': OWNER_PHONE, 'liveStatus': 'do_not_disturb'})
        r = self.post('/api/v1/vehicles/veh1/sms', {'message': 'hi'}, uid='scanner')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.error_code(r), 'failed-precondition')
        send.assert_not_called()

    def test_owner_sms_turned_off_is_refused(self, send):
        self.seed_vehicle()
        self.db.put('users/owner1/user-settings/owner1', {'enableSms': False})
        r = self.post('/api/v1/vehicles/veh1/sms', {'message': 'hi'}, uid='scanner')
        self.assertEqual(self.error_code(r), 'failed-precondition')
        send.assert_not_called()

    def test_blocked_scanner_is_refused(self, send):
        self.seed_vehicle()
        self.db.put('blocked_users/b1', {'blockerId': 'owner1', 'blockedUserId': 'scanner'})
        r = self.post('/api/v1/vehicles/veh1/sms', {'message': 'hi'}, uid='scanner')
        self.assertEqual(r.status_code, 403)
        send.assert_not_called()

    def test_family_assignment_number_is_used(self, send):
        from datetime import datetime, timedelta, timezone
        self.seed_vehicle(assignedFamilyMemberContact='9123456780',
                          assignedFamilyMemberId='fm1',
                          assignedUntil=datetime.now(timezone.utc) + timedelta(days=1))
        self.post('/api/v1/vehicles/veh1/sms', {'message': 'hi'}, uid='scanner')
        self.assertEqual(send.call_args.kwargs['digits_10'], '9123456780')

    def test_message_length_and_empty(self, send):
        self.seed_vehicle()
        self.assertEqual(self.post('/api/v1/vehicles/veh1/sms', {'message': '  '}, uid='s').status_code, 400)
        self.assertEqual(self.post('/api/v1/vehicles/veh1/sms', {'message': 'x' * 201}, uid='s').status_code, 400)
        send.assert_not_called()

    def test_scanner_rate_limit(self, send):
        self.seed_vehicle()
        codes = [self.post('/api/v1/vehicles/veh1/sms', {'message': 'hi'}, uid='s').status_code for _ in range(6)]
        self.assertEqual(codes, [200] * 5 + [429])

    def test_provider_failure_is_unavailable(self, send):
        send.return_value = {'ok': False, 'error': 'x'}
        self.seed_vehicle()
        r = self.post('/api/v1/vehicles/veh1/sms', {'message': 'hi'}, uid='s')
        self.assertEqual(r.status_code, 503)


# ─── Call registration ────────────────────────────────────────────────────────
class CallRegisterTests(ApiTestBase):
    def test_from_must_be_callers_own_number(self):
        self.db.put('users/u1', {'contactNumber': '9000000001'})
        with mock.patch('call_routing.views.register_call_destination') as view:
            r = self.post('/api/v1/calls/register', {'from': '9000000002', 'destination': OWNER_PHONE}, uid='u1')
        self.assertEqual(r.status_code, 403)
        view.assert_not_called()

    def test_own_number_runs_existing_view(self):
        self.db.put('users/u1', {'contactNumber': '9000000001'})
        with mock.patch('call_routing.views.register_call_destination',
                        return_value=JsonResponse({'status': 'ok'})) as view:
            r = self.post('/api/v1/calls/register', {'from': '+91 90000 00001', 'qr_id': 'q1'}, uid='u1')
        self.assertEqual(r.json(), {'status': 'ok'})
        view.assert_called_once()

    def test_requires_sign_in(self):
        self.assertEqual(self.post('/api/v1/calls/register', {'from': '9000000001'}).status_code, 401)


# ─── Private documents ────────────────────────────────────────────────────────
class DocumentTests(ApiTestBase):
    def upload(self, uid='owner1', content=JPEG, vehicle='veh1', **fields):
        data = {'documentType': 'rcBook', 'documentName': 'RC Book', 'expiryDate': '2030-01-31', **fields,
                'file': io.BytesIO(content)}
        data['file'].name = 'rc.jpg'
        return self.client.post(f'/api/v1/vehicles/{vehicle}/documents', data=data,
                                HTTP_AUTHORIZATION=f'Bearer good-{uid}')

    def test_upload_stores_privately_and_writes_firestore_row(self):
        self.seed_vehicle()
        r = self.upload()
        self.assertEqual(r.status_code, 201, r.content)
        body = r.json()
        stored = PrivateFile.objects.get(id=body['id'])
        self.assertEqual(stored.content_type, 'image/jpeg')
        row = self.db.docs[f'vehicleDocuments/{body["id"]}']
        self.assertEqual(row['documentUrl'], f'https://sudotag.com/api/v1/documents/{body["id"]}/file')
        self.assertEqual(row['storage'], 'private')
        self.assertEqual(row['vehicleNumber'], 'KL07AB1234')
        self.assertEqual(row['expiryDate'].year, 2030)
        self.assertNotIn('cloudinary', json.dumps(body))

    def test_cannot_upload_to_someone_elses_vehicle(self):
        self.seed_vehicle()
        self.assertEqual(self.upload(uid='stranger').status_code, 403)
        self.assertEqual(PrivateFile.objects.count(), 0)

    def test_rejects_non_image_bytes_and_bad_type(self):
        self.seed_vehicle()
        self.assertEqual(self.upload(content=b'<html>not an image</html>').status_code, 400)
        self.assertEqual(self.upload(documentType='passport').status_code, 400)

    def test_firestore_failure_leaves_no_file_behind(self):
        self.seed_vehicle()
        self.db.fail_writes = True
        self.assertEqual(self.upload().status_code, 500)
        self.assertEqual(PrivateFile.objects.count(), 0)
        import os
        leftovers = [f for _, _, files in os.walk(self.media) for f in files]
        self.assertEqual(leftovers, [])

    def test_owner_downloads_stranger_gets_404(self):
        self.seed_vehicle()
        doc_id = self.upload().json()['id']
        r = self.client.get(f'/api/v1/documents/{doc_id}/file', HTTP_AUTHORIZATION='Bearer good-owner1')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(b''.join(r.streaming_content), JPEG)
        self.assertEqual(r['Cache-Control'], 'private, no-store')
        r = self.client.get(f'/api/v1/documents/{doc_id}/file', HTTP_AUTHORIZATION='Bearer good-stranger')
        self.assertEqual(r.status_code, 404)

    def test_uploader_keeps_access_after_vehicle_is_gone(self):
        self.seed_vehicle()
        doc_id = self.upload().json()['id']
        del self.db.docs['vehicles/veh1']
        r = self.client.get(f'/api/v1/documents/{doc_id}/file', HTTP_AUTHORIZATION='Bearer good-owner1')
        self.assertEqual(r.status_code, 200)

    def test_delete_removes_row_file_and_record(self):
        self.seed_vehicle()
        doc_id = self.upload().json()['id']
        path = PrivateFile.objects.get(id=doc_id).storage_path
        self.assertEqual(self.client.delete(f'/api/v1/documents/{doc_id}',
                                            HTTP_AUTHORIZATION='Bearer good-stranger').status_code, 404)
        r = self.client.delete(f'/api/v1/documents/{doc_id}', HTTP_AUTHORIZATION='Bearer good-owner1')
        self.assertEqual(r.status_code, 204)
        self.assertNotIn(f'vehicleDocuments/{doc_id}', self.db.docs)
        self.assertFalse(PrivateFile.objects.filter(id=doc_id).exists())
        import os
        self.assertFalse(os.path.exists(os.path.join(self.media, path)))

    def test_legacy_cloudinary_row_has_no_private_file(self):
        self.seed_vehicle()
        self.db.put('vehicleDocuments/old', {'vehicleId': 'veh1', 'userId': 'owner1',
                                             'documentUrl': 'https://res.cloudinary.com/x/image/upload/a.jpg'})
        r = self.client.get('/api/v1/documents/old/file', HTTP_AUTHORIZATION='Bearer good-owner1')
        self.assertEqual(r.status_code, 404)


# ─── Management commands ──────────────────────────────────────────────────────
class DocumentCommandTests(ApiTestBase):
    def seed_legacy(self, doc_id='old1'):
        self.db.put(f'vehicleDocuments/{doc_id}', {
            'vehicleId': 'veh1', 'userId': 'owner1', 'documentType': 'rcBook',
            'documentUrl': f'https://res.cloudinary.com/demo/image/upload/v1/vehicle_documents/{doc_id}.jpg',
        })

    def _download(self, body=JPEG):
        response = mock.Mock()
        response.raise_for_status = mock.Mock()
        response.iter_content = lambda size: [body]
        return mock.patch('api.management.commands.migrate_vehicle_documents.requests.get', return_value=response)

    def test_dry_run_writes_nothing(self):
        self.seed_legacy()
        with self._download() as get:
            call_command('migrate_vehicle_documents', stdout=io.StringIO())
        get.assert_not_called()
        self.assertEqual(PrivateFile.objects.count(), 0)
        self.assertIn('cloudinary', self.db.docs['vehicleDocuments/old1']['documentUrl'])

    def test_apply_copies_and_repoints_and_is_rerunnable(self):
        self.seed_legacy()
        with self._download():
            call_command('migrate_vehicle_documents', '--apply', stdout=io.StringIO())
            call_command('migrate_vehicle_documents', '--apply', stdout=io.StringIO())
        stored = PrivateFile.objects.get(id='old1')
        row = self.db.docs['vehicleDocuments/old1']
        self.assertEqual(row['storage'], 'private')
        self.assertTrue(row['documentUrl'].endswith('/api/v1/documents/old1/file'))
        self.assertIn('cloudinary', row['legacyDocumentUrl'])
        self.assertEqual(stored.legacy_url, row['legacyDocumentUrl'])
        self.assertEqual(PrivateFile.objects.count(), 1)

    def test_non_image_download_is_not_stored(self):
        self.seed_legacy()
        err = io.StringIO()
        with self._download(body=b'<html>error page</html>'):
            call_command('migrate_vehicle_documents', '--apply', stdout=io.StringIO(), stderr=err)
        self.assertEqual(PrivateFile.objects.count(), 0)
        self.assertIn('FAILED old1', err.getvalue())

    def test_delete_public_only_after_copy(self):
        self.seed_legacy()
        with self._download(), mock.patch('admin_app.vehicle_photos.delete_storage_url') as destroy:
            call_command('migrate_vehicle_documents', '--apply', '--delete-public', stdout=io.StringIO())
        destroy.assert_called_once()
        self.assertEqual(PrivateFile.objects.get(id='old1').legacy_url, '')

    def test_cleanup_removes_orphans_only_with_apply(self):
        self.seed_vehicle()
        doc_id = DocumentTests.upload(self).json()['id']
        del self.db.docs[f'vehicleDocuments/{doc_id}']
        call_command('cleanup_orphan_documents', stdout=io.StringIO())
        self.assertTrue(PrivateFile.objects.filter(id=doc_id).exists())
        call_command('cleanup_orphan_documents', '--apply', stdout=io.StringIO())
        self.assertFalse(PrivateFile.objects.filter(id=doc_id).exists())


# ─── Legacy /admin/api/lost-mode-enabled/ hardening ───────────────────────────
class LegacyLostModeWebhookTests(ApiTestBase):
    def setUp(self):
        super().setUp()
        p = mock.patch('admin_app.views.db', self.db)
        p.start()
        self.addCleanup(p.stop)
        self.notify = mock.patch('admin_app.lost_mode_enabled_notify.notify_owner_lost_mode_enabled',
                                 return_value={'sms_sent': True, 'history_id': 'h'}).start()
        self.addCleanup(mock.patch.stopall)

    def call(self, **body):
        return self.post('/admin/api/lost-mode-enabled/', {'vehicle_id': 'veh1', 'is_lost_mode': True, **body})

    def test_force_flag_no_longer_bypasses_firestore(self):
        self.seed_vehicle(isLostMode=False)
        r = self.call(force=True, source='mobile')
        self.assertEqual(r.json()['skipped_reason'], 'not_lost_mode_in_firestore')
        self.notify.assert_not_called()

    def test_caller_text_is_ignored_and_repeat_is_suppressed(self):
        self.seed_vehicle(isLostMode=True)
        self.assertTrue(self.call(sms_body='Send money to …').json()['sms_sent'])
        self.assertEqual(self.notify.call_args.kwargs['sms_body_override'], '')
        self.assertEqual(self.call().json()['skipped_reason'], 'recently_sent')
        self.assertEqual(self.notify.call_count, 1)

    def tearDown(self):
        RateLimitBucket.objects.all().delete()
