from datetime import date, datetime, timedelta
from unittest import mock

import pytz
from django.test import SimpleTestCase

from admin_app import analytics
from admin_app.analytics_views import bars, decorate

IST = pytz.timezone('Asia/Kolkata')
TODAY = date(2026, 11, 20)


def at(d, hour=10):
    return IST.localize(datetime(d.year, d.month, d.day, hour))


def ago(n, hour=10):
    return at(TODAY - timedelta(days=n), hour)


def sample():
    return {
        'users': [
            {'_id': 'u1', 'createdAt': ago(0), 'city': 'kochi', 'appPlatform': 'ios', 'profileComplete': True},
            {'_id': 'u2', 'createdAt': ago(3), 'city': 'Kochi', 'appPlatform': 'android'},
            {'_id': 'u3', 'createdAt': ago(40), 'city': 'Calicut'},
            {'_id': 'admin', 'createdAt': ago(1), 'emailAddress': 'sudotagonline@gmail.com'},
            {'_id': 'bridge', 'createdAt': ago(1), 'purpose': 'multipurpose_call_bridge'},
            {'_id': 'gone', 'createdAt': ago(1), 'accountDeleted': True},
        ],
        'vehicles': [
            {'_id': 'v1', 'ownerId': 'u1', 'createdAt': ago(0), 'vehicleType': 'car', 'make': 'Maruti'},
            {'_id': 'v2', 'ownerId': 'u2', 'createdAt': ago(35), 'vehicleType': 'bike', 'make': 'Honda'},
        ],
        'qrcodes': [
            {'_id': 'q1', 'isAssigned': True, 'userID': 'u1', 'createdDateTime': ago(10), 'assignedAt': ago(0)},
            {'_id': 'q2', 'isAssigned': False, 'createdDateTime': ago(10)},
            {'_id': 'q3', 'isAssigned': True, 'userID': 'u2'},  # old activation with no date
            {'_id': 'q4', 'purpose': 'multipurpose_call_bridge', 'isAssigned': True},
        ],
        'orders': [
            {'_id': 'o1', 'timestamp': ago(2), 'amount': 499, 'paymentStatus': 'paid', 'orderStatus': 3, 'source': 'website'},
            {'_id': 'o2', 'timestamp': ago(45), 'amount': 299, 'paymentStatus': 'paid', 'orderStatus': 1},
            {'_id': 'o3', 'timestamp': ago(1), 'amount': 999, 'paymentStatus': 'pending', 'orderStatus': 0},
        ],
        'community_posts': [
            {'_id': 'p1', 'createdAt': ago(5), 'category': 'traffic', 'reportsCount': 2},
            {'_id': 'p2', 'createdAt': ago(6), 'category': 'traffic', 'isDeleted': True},
        ],
        'multipurpose_qrs': [
            {'_id': 't1', 'purpose': 'multipurpose', 'isAssigned': True, 'categoryLabel': 'Pet', 'scanCount': 4},
            {'_id': 't2', 'purpose': 'other'},
        ],
    }


class ComputeTests(SimpleTestCase):
    def setUp(self):
        self.s = analytics.compute(sample(), 30, today=TODAY)
        self.kpi = {k['key']: k for k in self.s['kpis']}

    def test_leaves_out_admin_bridge_and_deleted_accounts(self):
        self.assertEqual(self.s['funnel'][0]['value'], 3)

    def test_kpis_count_current_window_and_compare_to_previous(self):
        self.assertEqual(self.kpi['users']['value'], 2)
        self.assertEqual(self.kpi['users']['prev'], 1)
        self.assertEqual(self.kpi['users']['delta'], 100)
        self.assertEqual(self.kpi['revenue']['value'], 499)  # pending order not counted
        self.assertEqual(self.kpi['revenue']['prev'], 299)
        self.assertEqual(self.kpi['activations']['value'], 1)
        self.assertIsNone(self.kpi['activations']['delta'])  # nothing before to compare

    def test_daily_buckets_end_today(self):
        g = self.s['growth']
        self.assertEqual(self.s['unit'], 'day')
        self.assertEqual(len(g['labels']), 30)
        self.assertEqual(g['labels'][-1], '20 Nov')
        self.assertEqual(g['series'][0]['data'][-1], 1)  # u1 signed up today
        self.assertEqual(sum(g['series'][0]['data']), 2)

    def test_cumulative_starts_from_earlier_customers(self):
        self.assertEqual(self.s['cumulative']['start'], 1)  # u3 joined 40 days ago
        self.assertEqual(self.s['cumulative']['data'][-1], 3)

    def test_funnel(self):
        values = [f['value'] for f in self.s['funnel']]
        self.assertEqual(values, [3, 2, 2])
        self.assertEqual(self.s['profile']['value'], 1)

    def test_categories_are_tidied_and_merged(self):
        self.assertEqual(self.s['cities'][0], ('Kochi', 2))
        self.assertIn(('iOS', 1), self.s['platforms'])

    def test_qr_stock_ignores_bridge_and_reports_undated(self):
        qr = self.s['qr']
        self.assertEqual((qr['total'], qr['assigned'], qr['unassigned']), (3, 2, 1))
        self.assertEqual(qr['median_wait'], 10)
        self.assertEqual(qr['undated'], 1)

    def test_civic_and_smart_tags(self):
        self.assertEqual(dict(self.s['civic']['states']), {'Live': 0, 'Reported': 1, 'Pending': 0, 'Removed': 1})
        self.assertEqual(self.s['smart']['total'], 1)
        self.assertEqual(self.s['smart']['scans'], 4)

    def test_weekly_and_monthly_ranges(self):
        year = analytics.compute(sample(), 365, today=TODAY)
        self.assertEqual(year['unit'], 'week')
        self.assertTrue(50 <= len(year['growth']['labels']) <= 54)
        every = analytics.compute(sample(), 0, today=TODAY)
        self.assertEqual(every['unit'], 'month')
        self.assertEqual(every['growth']['labels'][-1], 'Nov 26')
        self.assertIsNone(every['kpis'][0]['delta'])

    def test_empty_data(self):
        s = analytics.compute({}, 7, today=TODAY)
        self.assertEqual(s['funnel'][0]['value'], 0)
        self.assertEqual(s['heatmap']['total'], 0)
        decorate(s)  # no division by zero

    def test_top_counts_folds_rest_into_other(self):
        self.assertEqual(analytics.top_counts(list('aaabbc'), 2), [('a', 3), ('b', 2), ('Other', 1)])

    def test_parse_range(self):
        self.assertEqual(analytics.parse_range('90'), ('90', 90))
        self.assertEqual(analytics.parse_range('nope'), ('30', 30))


class DecorateTests(SimpleTestCase):
    def test_bars_scale_to_largest(self):
        self.assertEqual(bars([('a', 4), ('b', 1)]), [
            {'label': 'a', 'value': 4, 'pct': 100.0}, {'label': 'b', 'value': 1, 'pct': 25.0}])

    def test_heat_levels(self):
        s = decorate(analytics.compute(sample(), 30, today=TODAY))
        levels = {c['level'] for row in s['heatmap']['grid'] for c in row['cells']}
        self.assertIn(0, levels)
        self.assertIn(5, levels)


class PageTests(SimpleTestCase):
    databases = {'default'}

    def test_requires_login(self):
        self.assertEqual(self.client.get('/admin/analytics/').status_code, 302)

    def test_renders_charts(self):
        session = self.client.session
        session['admin'] = True
        session.save()
        raw = dict(sample(), loaded_at=at(TODAY))
        with mock.patch.object(analytics, 'load', return_value=raw), \
             mock.patch('admin_app.context_processors.civic_sense_badge', return_value={}):
            r = self.client.get('/admin/analytics/?range=7')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'id="growth-chart"')
        self.assertContains(r, 'Customer journey')
        self.assertContains(r, 'aria-current="page">7D<')


class InsightTests(SimpleTestCase):
    def setUp(self):
        self.n = analytics.insights(analytics.compute(sample(), 30, today=TODAY))

    def test_unpaid_orders_are_flagged(self):
        self.assertEqual(self.n['revenue']['tone'], 'alert')
        self.assertIn('₹999', self.n['revenue']['headline'])

    def test_reported_civic_post_is_flagged(self):
        self.assertEqual(self.n['civic']['tone'], 'alert')
        self.assertEqual(self.n['civic']['url'], 'civic_sense_reports')

    def test_top_is_ranked_and_capped(self):
        top = self.n['top']
        self.assertLessEqual(len(top), 4)
        self.assertEqual([t['weight'] for t in top], sorted((t['weight'] for t in top), reverse=True))

    def test_low_qr_stock_is_urgent(self):
        self.assertEqual(self.n['qr']['tone'], 'alert')  # only 1 sticker left in the sample
        self.assertEqual(self.n['top'][0]['headline'], self.n['qr']['headline'])

    def test_resolve_turns_names_into_links(self):
        notes = analytics.resolve(self.n)
        self.assertEqual(notes['qr']['url'], '/admin/generate-qr/')

    def test_empty_data_has_no_crash(self):
        n = analytics.insights(analytics.compute({}, 30, today=TODAY))
        self.assertIn('No new customers', n['growth']['headline'])

    def test_inr_format(self):
        self.assertEqual(analytics._inr(1598), '₹1,598')
        self.assertEqual(analytics._inr(1234567), '₹12,34,567')


class IndiaTimeTests(SimpleTestCase):
    def test_date_filter_shows_india_time(self):
        from datetime import timezone as dt_tz
        from django.template import Context, Template
        from django.test import RequestFactory
        from django.utils import timezone
        from admin_app.middleware import IndiaTimeMiddleware

        stored = datetime(2026, 11, 19, 16, 47, tzinfo=dt_tz.utc)  # what Firestore returns
        out = {}

        def view(request):
            out['html'] = Template('{% load custom_filters %}{{ t|to_ist|date:"g:i A" }}').render(Context({'t': stored}))
            return None

        IndiaTimeMiddleware(view)(RequestFactory().get('/'))
        self.assertEqual(out['html'], '10:17 PM')
        self.assertEqual(timezone.get_current_timezone_name(), 'UTC')  # reset after the request


class ActivityTests(SimpleTestCase):
    def test_feed_is_newest_first_and_named(self):
        data = sample()
        data['users'][0]['fullName'] = 'arjun pandath'
        feed = analytics.activity(data, 5)
        times = [e['at'] for e in feed]
        self.assertEqual(times, sorted(times, reverse=True))
        self.assertTrue(any(e['text'].startswith('Arjun joined') for e in feed))
        self.assertTrue(all('iso' in e for e in feed))

    def test_month_pace(self):
        p = analytics.month_pace(sample(), today=TODAY)
        users = p['items'][0]
        self.assertEqual(p['day'], 20)
        self.assertEqual(users['now'], 2)  # u1 today, u2 3 days ago; u3 was in October
        self.assertEqual(users['last'], 1)
        self.assertEqual(users['projected'], 3)  # 2 in 20 days -> 3 over 30
