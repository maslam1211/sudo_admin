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
