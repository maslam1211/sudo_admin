import time
from types import SimpleNamespace
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from admin_app import admin_security as sec

RFC_SECRET = 'GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ'  # base32 of "12345678901234567890"


class TotpTests(SimpleTestCase):
    def test_rfc6238_vectors(self):
        # RFC 6238 appendix B, SHA-1, last 6 digits.
        for t, code in ((59, '287082'), (1111111109, '081804'), (1234567890, '005924'), (2000000000, '279037')):
            self.assertEqual(sec.totp_at(RFC_SECRET, t // 30), code)

    def test_verify_allows_one_step_drift_and_blocks_reuse(self):
        now = 1_800_000_000
        step = sec.current_step(now)
        self.assertEqual(sec.verify_totp(RFC_SECRET, sec.totp_at(RFC_SECRET, step), now=now), step)
        self.assertEqual(sec.verify_totp(RFC_SECRET, sec.totp_at(RFC_SECRET, step - 1), now=now), step - 1)
        self.assertIsNone(sec.verify_totp(RFC_SECRET, sec.totp_at(RFC_SECRET, step - 2), now=now))
        self.assertIsNone(sec.verify_totp(RFC_SECRET, sec.totp_at(RFC_SECRET, step), now=now, last_step=step))
        self.assertIsNone(sec.verify_totp(RFC_SECRET, 'abc', now=now))
        self.assertEqual(sec.verify_totp(RFC_SECRET, ' ' + sec.totp_at(RFC_SECRET, step)[:3] + ' ' + sec.totp_at(RFC_SECRET, step)[3:], now=now), step)

    def test_new_secret_and_uri(self):
        s = sec.new_totp_secret()
        self.assertEqual(len(s), 32)
        uri = sec.otpauth_uri(s, 'a@sudotag.com')
        self.assertTrue(uri.startswith('otpauth://totp/SudoTag%20Admin%3Aa%40sudotag.com?secret='))
        self.assertIn('issuer=SudoTag%20Admin', uri)
        self.assertTrue(sec.qr_data_uri(uri).startswith('data:image/png;base64,'))

    def test_secret_is_encrypted(self):
        token = sec.encrypt(RFC_SECRET)
        self.assertNotIn(RFC_SECRET, token)
        self.assertEqual(sec.decrypt(token), RFC_SECRET)
        with override_settings(ADMIN_2FA_KEY='another-key'):
            with self.assertRaises(Exception):
                sec.decrypt(token)


@override_settings(ADMIN_PANEL_PASSWORD='Shared#Pass2026')
class PasswordTests(SimpleTestCase):
    def test_rules(self):
        self.assertEqual(sec.validate_new_password('Strong#Pass99', 'x@y.com'), 'Strong#Pass99')
        for bad, msg in (('short1A!', 'at least'), ('alllowercase', 'Mix'), ('Shared#Pass2026', 'shared'),
                         ('Aslam#Pass99', 'email'), (' Strong#Pass99', 'space')):
            with self.assertRaisesMessage(sec.SecurityError, msg):
                sec.validate_new_password(bad, 'aslam@sudotag.com')

    def test_hash(self):
        h = sec.hash_password('Strong#Pass99')
        self.assertNotIn('Strong#Pass99', h)
        self.assertTrue(sec.password_ok('Strong#Pass99', h))
        self.assertFalse(sec.password_ok('Strong#Pass98', h))
        self.assertFalse(sec.password_ok('', h))


class LockTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def test_five_failures_lock_for_15_minutes(self):
        for left in (4, 3, 2, 1):
            self.assertEqual(sec.record_failure('pw', 'a'), left)
        self.assertEqual(sec.record_failure('pw', 'a'), 0)
        with self.assertRaisesMessage(sec.SecurityError, 'Too many wrong tries'):
            sec.check_not_locked('pw', 'a')
        sec.check_not_locked('pw', 'b')  # other people unaffected
        sec.clear_failures('pw', 'a')
        sec.check_not_locked('pw', 'a')


class SessionExpiryTests(SimpleTestCase):
    def test_idle_and_absolute_limits(self):
        now = 1_800_000_000
        self.assertIsNone(sec.session_expired({'admin': True, 'admin_login_at': now - 60, 'admin_last_seen': now - 60}, now))
        self.assertIn('30 minutes', sec.session_expired({'admin': True, 'admin_login_at': now - 3600, 'admin_last_seen': now - 31 * 60}, now))
        self.assertIn('12 hours', sec.session_expired({'admin': True, 'admin_login_at': now - 13 * 3600, 'admin_last_seen': now}, now))
        legacy = {'admin': True}
        self.assertIsNone(sec.session_expired(legacy, now))
        self.assertEqual(legacy['admin_login_at'], now)
        self.assertIsNone(sec.session_expired({}, now))


def user_doc(uid='u1', email='boss@sudotag.com', role=1):
    return SimpleNamespace(id=uid, to_dict=lambda: {'emailAddress': email, 'roleId': role})


@override_settings(ADMIN_PANEL_PASSWORD='Shared#Pass2026', ADMIN_GATE_PIN='2468')
class SignInFlowTests(SimpleTestCase):
    databases = {'default'}

    def setUp(self):
        cache.clear()
        self.accounts = {}
        self.db = mock.MagicMock()
        self.db.collection.return_value.where.return_value.stream.side_effect = lambda: iter([user_doc()])
        patches = [
            mock.patch('admin_app.views.db', self.db),
            mock.patch('admin_app.admin_auth_views._db', return_value=self.db),
            mock.patch.object(sec, 'get_account', side_effect=lambda db, uid: dict(self.accounts.get(uid, {}))),
            mock.patch.object(sec, 'save_setup', side_effect=self._save_setup),
            mock.patch.object(sec, 'mark_code_used', side_effect=lambda db, uid, step: self.accounts[uid].update(lastTotpStep=step)),
            mock.patch.object(sec, 'log_event'),
            mock.patch('admin_app.context_processors.civic_sense_badge', return_value={}),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        s = self.client.session
        s['auth_pin_verified'] = True
        s.save()

    def _save_setup(self, db, uid, email, password, secret, step):
        self.accounts[uid] = {'passwordHash': sec.hash_password(password), 'totpSecretEnc': sec.encrypt(secret),
                              'totpEnabled': True, 'lastTotpStep': step}

    def login(self, password):
        return self.client.post('/admin/login/', {'email': 'Boss@SudoTag.com', 'password': password})

    def test_first_time_then_normal_sign_in(self):
        # 1. Shared password works once and goes to setup, not into the panel.
        r = self.login('Shared#Pass2026')
        self.assertRedirects(r, '/admin/security/setup/', fetch_redirect_response=False)
        self.assertFalse(self.client.session.get('admin'))
        self.assertEqual(self.client.get('/admin/dashboard/').status_code, 302)

        # 2. Setup page shows a QR; wrong code is refused; right code signs in.
        page = self.client.get('/admin/security/setup/')
        self.assertContains(page, 'data:image/png;base64,')
        secret = sec.decrypt(self.client.session['admin_setup_secret'])
        bad = self.client.post('/admin/security/setup/', {'password': 'Strong#Pass99', 'password2': 'Strong#Pass99', 'code': '000000'})
        self.assertContains(bad, 'That code is not right')
        code = sec.totp_at(secret, sec.current_step())
        r = self.client.post('/admin/security/setup/', {'password': 'Strong#Pass99', 'password2': 'Strong#Pass99', 'code': code})
        self.assertRedirects(r, '/admin/dashboard/', fetch_redirect_response=False)
        self.assertTrue(self.client.session.get('admin'))
        self.assertNotIn('admin_setup_secret', self.client.session)

        # 3. Next time: shared password no longer works; personal one + code does.
        self.client.get('/admin/logout/')
        self.client.cookies.pop('sessionid', None)  # logout leaves an empty cookie behind
        s = self.client.session
        s['auth_pin_verified'] = True
        s.save()
        self.assertContains(self.login('Shared#Pass2026'), 'Invalid email or password')
        r = self.login('Strong#Pass99')
        self.assertRedirects(r, '/admin/login/2fa/', fetch_redirect_response=False)
        self.assertFalse(self.client.session.get('admin'))
        # The code used during setup can't be replayed.
        self.assertContains(self.client.post('/admin/login/2fa/', {'code': code}), 'not right')
        nxt = sec.totp_at(secret, sec.current_step() + 1)
        r = self.client.post('/admin/login/2fa/', {'code': nxt})
        self.assertRedirects(r, '/admin/dashboard/', fetch_redirect_response=False)
        self.assertTrue(self.client.session.get('admin'))

    def test_non_admin_and_unknown_email_get_the_same_message(self):
        self.db.collection.return_value.where.return_value.stream.side_effect = lambda: iter([user_doc(role=2)])
        self.assertContains(self.login('Shared#Pass2026'), 'Invalid email or password')
        self.db.collection.return_value.where.return_value.stream.side_effect = lambda: iter([])
        self.assertContains(self.login('Shared#Pass2026'), 'Invalid email or password')

    def test_password_locks_after_five_wrong_tries(self):
        for _ in range(4):
            self.assertContains(self.login('nope'), 'left')
        self.assertContains(self.login('nope'), 'locked for 15 minutes')
        self.assertContains(self.login('Shared#Pass2026'), 'Too many wrong tries')

    def test_cannot_skip_to_setup_or_code_without_password(self):
        self.assertEqual(self.client.get('/admin/security/setup/').status_code, 302)
        self.assertEqual(self.client.get('/admin/login/2fa/').status_code, 302)


class SessionGuardTests(SimpleTestCase):
    databases = {'default'}

    def test_idle_session_is_signed_out(self):
        s = self.client.session
        s['admin'] = True
        s['admin_login_at'] = time.time() - 3600
        s['admin_last_seen'] = time.time() - 31 * 60
        s.save()
        r = self.client.get('/admin/dashboard/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/admin/verify-auth-pin/', r['Location'])
        self.assertFalse(self.client.session.get('admin'))
