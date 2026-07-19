"""Regression tests for public referral invite landing URLs."""
from django.test import SimpleTestCase, override_settings
from django.urls import reverse, resolve


@override_settings(ROOT_URLCONF='sudo_admin.urls')
class ReferralInviteUrlTests(SimpleTestCase):
    def test_accepts_path_without_trailing_slash(self):
        match = resolve('/r/SUDOA1B2C3D4')
        self.assertEqual(match.url_name, 'referral_invite')
        self.assertEqual(match.kwargs['code'], 'SUDOA1B2C3D4')

    def test_accepts_path_with_trailing_slash(self):
        match = resolve('/r/SUDOA1B2C3D4/')
        self.assertEqual(match.url_name, 'referral_invite')
        self.assertEqual(match.kwargs['code'], 'SUDOA1B2C3D4')

    def test_reverse_produces_slashless_mobile_style_link(self):
        # Mobile CF emits https://sudotag.com/r/{CODE} (no trailing slash).
        url = reverse('referral_invite', kwargs={'code': 'SUDOA1B2C3D4'})
        self.assertIn('/r/SUDOA1B2C3D4', url)
        # Prefer slashless so reverse() matches shared links.
        self.assertFalse(url.endswith('/r/SUDOA1B2C3D4/'))
