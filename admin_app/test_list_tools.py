from django.test import RequestFactory, SimpleTestCase

from admin_app import list_tools


class ListToolsTests(SimpleTestCase):
    row = {'fullName': 'Arjun Pandath', 'contactNumber': '+91 98765 43210', 'address': {'city': 'Kozhikode'}}

    def test_matches_every_word_any_field(self):
        f = ('fullName', 'contactNumber', 'address.city')
        self.assertTrue(list_tools.matches(self.row, 'arjun kozhikode', f))
        self.assertFalse(list_tools.matches(self.row, 'arjun bengaluru', f))
        self.assertTrue(list_tools.matches(self.row, '', f))

    def test_phone_digits_match_without_spaces(self):
        self.assertTrue(list_tools.matches(self.row, '9876543210', ('contactNumber',)))
        self.assertTrue(list_tools.matches(self.row, '3210', ('contactNumber',)))

    def test_query_string_keeps_filters_drops_page(self):
        req = RequestFactory().get('/x', {'q': 'kia', 'page': '3', 'status': '1', 'export': 'csv'})
        self.assertEqual(list_tools.query_string(req), 'q=kia&status=1&')

    def test_csv_blocks_formulas_and_formats(self):
        r = list_tools.csv_response('t', [('Name', 'fullName'), ('City', 'address.city')],
                                    [{'fullName': '=HYPERLINK("x")', 'address': {'city': 'Kochi'}}])
        body = r.content.decode('utf-8-sig')
        self.assertIn('\'=HYPERLINK', body)
        self.assertIn('Kochi', body)
        self.assertIn('attachment; filename="t-', r['Content-Disposition'])


class AdminAssetTests(SimpleTestCase):
    def test_theme_files_served_without_login(self):
        for path in ('assets/css/sudotag-admin.css', 'assets/js/sudotag-ui.js'):
            r = self.client.get('/admin/assets/' + path + '?v=1')
            self.assertEqual(r.status_code, 200, path)
            self.assertIn('immutable', r['Cache-Control'])
        self.assertTrue(self.client.get('/admin/assets/assets/css/sudotag-admin.css')['Content-Type'].startswith('text/css'))

    def test_other_files_refused(self):
        for path in ('../settings.py', 'assets/css/main.css', '/etc/passwd', 'assets/js/../../../manage.py'):
            self.assertEqual(self.client.get('/admin/assets/' + path).status_code, 404, path)

    def test_template_tag_versions_url(self):
        from admin_app.templatetags.admin_assets import admin_asset
        url = admin_asset('assets/css/sudotag-admin.css')
        self.assertRegex(url, r'^/admin/assets/assets/css/sudotag-admin\.css\?v=\d+$')
