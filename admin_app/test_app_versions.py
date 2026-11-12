"""App Version Management: rules shared with the mobile app, validation, API auth."""
import json
from unittest import mock

from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse

from admin_app import app_version_service as svc


class CompareAndDecideTests(SimpleTestCase):
    """Must match decideUpdate in lib/service/app_update/app_update_policy.dart."""

    def test_compare_versions(self):
        self.assertEqual(svc.compare_versions('1.10.0', '1.9.9'), 1)
        self.assertEqual(svc.compare_versions('1.2', '1.2.0'), 0)
        self.assertEqual(svc.compare_versions('1.1.53', '1.1.54'), -1)
        self.assertEqual(svc.compare_versions('2.0.0+5', '2.0.0'), 0)

    def test_decisions(self):
        d = svc.decide_update
        self.assertEqual(d(103, '1.1.53', None), 'none')
        self.assertEqual(d(103, '1.1.53', {'latestBuild': 103}), 'none')
        self.assertEqual(d(103, '1.1.53', {'latestBuild': 104}), 'optional')
        self.assertEqual(d(103, '1.1.53', {'latestBuild': 104, 'forceUpdate': True}), 'mandatory')
        self.assertEqual(d(103, '1.1.53', {'latestBuild': 110, 'minSupportedBuild': 104}), 'mandatory')
        self.assertEqual(d(103, '1.1.53', {'minSupportedBuild': 103}), 'none')
        # Kill switch.
        self.assertEqual(d(1, '1.0', {'updateEnabled': False, 'minSupportedBuild': 500}), 'none')
        # Versions when builds are missing.
        self.assertEqual(d(0, '1.1.53', {'latestVersion': '1.1.54'}), 'optional')
        self.assertEqual(d(0, '1.1.53', {'minSupportedVersion': '1.2.0'}), 'mandatory')
        # Garbage never locks anyone out.
        self.assertEqual(d(103, '1.1.53', {'minSupportedBuild': 'abc', 'forceUpdate': 'maybe'}), 'none')


class ValidationTests(SimpleTestCase):
    def good(self, **over):
        data = {
            'latest_version': '1.1.54', 'latest_build': '104',
            'minimum_supported_version': '1.1.40', 'minimum_supported_build': '90',
            'update_type': 'flexible', 'release_notes': '• Faster scans',
            'store_url': svc.DEFAULT_STORE_URLS['android'],
            'force_update': False, 'update_enabled': True,
        }
        data.update(over)
        return data

    def test_valid_android(self):
        clean, errors = svc.validate_config('android', self.good())
        self.assertEqual(errors, {})
        self.assertEqual(clean['latestBuild'], 104)
        self.assertEqual(clean['minSupportedBuild'], 90)
        self.assertEqual(clean['updateType'], 'flexible')
        self.assertTrue(clean['updateEnabled'])

    def test_store_url_defaults_and_must_match_platform(self):
        clean, errors = svc.validate_config('ios', self.good(store_url=''))
        self.assertEqual(errors, {})
        self.assertEqual(clean['storeUrl'], svc.DEFAULT_STORE_URLS['ios'])
        _, errors = svc.validate_config('ios', self.good(store_url=svc.DEFAULT_STORE_URLS['android']))
        self.assertIn('store_url', errors)
        _, errors = svc.validate_config('android', self.good(store_url='http://play.google.com/x'))
        self.assertIn('store_url', errors)
        _, errors = svc.validate_config('android', self.good(store_url='https://evil.example/apk'))
        self.assertIn('store_url', errors)

    def test_rejects_bad_numbers_and_ordering(self):
        for over, field in [
            ({'latest_version': '1.x'}, 'latest_version'),
            ({'latest_build': ''}, 'latest_build'),
            ({'latest_build': '-3'}, 'latest_build'),
            ({'latest_build': '0'}, 'latest_build'),
            ({'minimum_supported_build': '200'}, 'minimum_supported_build'),
            ({'minimum_supported_version': '2.0.0'}, 'minimum_supported_version'),
            ({'update_type': 'silent'}, 'update_type'),
            ({'release_notes': 'x' * 5000}, 'release_notes'),
        ]:
            _, errors = svc.validate_config('android', self.good(**over))
            self.assertIn(field, errors, over)

    def test_unknown_platform(self):
        with self.assertRaises(svc.UnknownPlatform):
            svc.validate_config('windows', self.good())

    def test_version_check_payload_is_computed_server_side(self):
        config = {'latestVersion': '1.1.54', 'latestBuild': 104, 'minSupportedBuild': 100,
                  'updateType': 'immediate', 'releaseNotes': 'n', 'storeUrl': 'https://play.google.com/x'}
        p = svc.version_check_payload('android', config, installed_build=99)
        self.assertTrue(p['update_available'])
        self.assertTrue(p['force_update'])
        p = svc.version_check_payload('android', config, installed_build=102)
        self.assertTrue(p['update_available'])
        self.assertFalse(p['force_update'])
        p = svc.version_check_payload('android', config, installed_build=104)
        self.assertFalse(p['update_available'])
        for key in ('platform', 'latest_version', 'latest_build', 'minimum_supported_version',
                    'minimum_supported_build', 'update_available', 'force_update', 'update_type',
                    'release_notes', 'store_url', 'update_enabled', 'published_at'):
            self.assertIn(key, p)
        empty = svc.version_check_payload('ios', None, installed_build=1)
        self.assertFalse(empty['update_available'])
        self.assertFalse(empty['update_enabled'])


CONFIG = {'latestVersion': '1.1.54', 'latestBuild': 104, 'minSupportedBuild': 100,
          'updateEnabled': True, 'storeUrl': svc.DEFAULT_STORE_URLS['android']}


@mock.patch.object(svc, 'get_db', return_value=object())
class ApiTests(TestCase):
    def login(self, client):
        session = client.session
        session['admin'] = True
        session['email'] = 'admin@sudotag.com'
        session.save()

    def csrf(self, client):
        from django.middleware.csrf import _get_new_csrf_string, _mask_cipher_secret
        secret = _get_new_csrf_string()
        client.cookies['csrftoken'] = secret
        return _mask_cipher_secret(secret)

    def test_version_check_public(self, _db):
        with mock.patch.object(svc, 'get_config', return_value=CONFIG):
            res = self.client.get('/api/v1/app/version-check', {'platform': 'android', 'build': '99'})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()['force_update'])
        self.assertEqual(self.client.get('/api/v1/app/version-check', {'platform': 'x'}).status_code, 400)
        self.assertEqual(self.client.get('/api/v1/app/version-check',
                                         {'platform': 'ios', 'build': 'abc'}).status_code, 400)

    def test_version_check_backend_down(self, _db):
        with mock.patch.object(svc, 'get_config', side_effect=RuntimeError('down')):
            res = self.client.get('/api/v1/app/version-check', {'platform': 'android'})
        self.assertEqual(res.status_code, 503)

    def test_admin_api_requires_admin(self, _db):
        self.assertEqual(self.client.get('/api/v1/admin/app-versions').status_code, 401)
        res = self.client.put('/api/v1/admin/app-versions/android', '{}', content_type='application/json')
        self.assertEqual(res.status_code, 401)

    def test_admin_write_requires_csrf_even_under_api(self, _db):
        client = Client(enforce_csrf_checks=True)
        self.login(client)
        with mock.patch.object(svc, 'publish_config') as publish:
            res = client.put('/api/v1/admin/app-versions/android',
                             json.dumps({'latest_version': '1.1.55', 'latest_build': 105}),
                             content_type='application/json')
        self.assertEqual(res.status_code, 403)
        publish.assert_not_called()

    def test_admin_put_publishes_with_csrf(self, _db):
        client = Client(enforce_csrf_checks=True)
        self.login(client)
        token = self.csrf(client)
        with mock.patch.object(svc, 'publish_config') as publish, \
                mock.patch.object(svc, 'get_config', return_value=CONFIG):
            res = client.put('/api/v1/admin/app-versions/android',
                             json.dumps({'latest_version': '1.1.55', 'latest_build': 105,
                                         'minimum_supported_build': 100}),
                             content_type='application/json', HTTP_X_CSRFTOKEN=token)
        self.assertEqual(res.status_code, 200, res.content)
        clean = publish.call_args.args[2]
        self.assertEqual(clean['latestBuild'], 105)
        self.assertEqual(publish.call_args.kwargs['admin_email'], 'admin@sudotag.com')

    def test_admin_validation_errors(self, _db):
        self.login(self.client)
        token = self.csrf(self.client)
        with mock.patch.object(svc, 'publish_config') as publish:
            res = self.client.post('/api/v1/admin/app-versions',
                                   json.dumps({'platform': 'android', 'latest_version': 'bad'}),
                                   content_type='application/json', HTTP_X_CSRFTOKEN=token)
        self.assertEqual(res.status_code, 400)
        self.assertIn('latest_version', res.json()['errors'])
        publish.assert_not_called()

    def test_admin_page_requires_admin(self, _db):
        self.assertEqual(self.client.get(reverse('manage_app_versions')).status_code, 302)
        res = self.client.post(reverse('publish_app_version', args=['android']), {})
        self.assertEqual(res.status_code, 302)


@mock.patch.object(svc, 'get_db', return_value=object())
class AdminPageTests(TestCase):
    def test_page_renders_configs_history_stats_and_logs(self, _db):
        from datetime import datetime, timezone
        session = self.client.session
        session['admin'] = True
        session.save()
        when = datetime(2026, 11, 13, 10, 0, tzinfo=timezone.utc)
        release = dict(CONFIG, publishedAt=when, publishedBy='admin@sudotag.com',
                       releaseNotes='• Faster scans', updateType='flexible', id='r1')
        with mock.patch.object(svc, 'get_config', side_effect=lambda db, p: CONFIG if p == 'android' else None), \
                mock.patch.object(svc, 'list_releases', side_effect=lambda db, p, limit=15: [release] if p == 'android' else []), \
                mock.patch.object(svc, 'adoption_stats', return_value={'reporting': 10, 'on_latest': 7, 'outdated': 3, 'below_minimum': 1, 'adoption_pct': 70.0}), \
                mock.patch.object(svc, 'recent_events', return_value=[{'platform': 'android', 'event': 'immediate_failed', 'version': '1.1.53', 'build': 103, 'error': 'ERROR_API_NOT_AVAILABLE', 'uid': 'u1', 'createdAt': when}]), \
                mock.patch.object(svc, 'total_users', return_value=25):
            res = self.client.get(reverse('manage_app_versions'))
        self.assertEqual(res.status_code, 200)
        html = res.content.decode()
        for text in ('App Version Management', 'Android', 'iOS', 'Not published yet', '1.1.54',
                     'Faster scans', '70.0%', 'ERROR_API_NOT_AVAILABLE', 'Publish Android configuration'):
            self.assertIn(text, html)
        # 25 users, 10 reporting on each platform (mocked for both).
        self.assertEqual(res.context['not_reported'], 5)
