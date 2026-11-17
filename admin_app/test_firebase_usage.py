"""Firebase usage page: day bucketing, cost estimate and access."""
import datetime as dt
from unittest import mock

from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from admin_app import firebase_usage as fu


class BucketTests(SimpleTestCase):
    def test_counts_sum_into_pacific_days(self):
        # 07:00Z and 08:00Z ends: the first hour belongs to the previous Pacific day (PST = UTC-8).
        points = [('2026-11-18T08:00:00Z', 5), ('2026-11-18T09:00:00Z', 7), ('2026-11-18T10:00:00Z', 1)]
        days = fu.bucket_by_day(points, gauge=False)
        self.assertEqual(days, {dt.date(2026, 11, 17): 5, dt.date(2026, 11, 18): 8})

    def test_gauge_keeps_latest_value(self):
        points = [('2026-11-18T12:00:00Z', 100), ('2026-11-18T20:00:00Z', 300), ('2026-11-18T15:00:00Z', 200)]
        self.assertEqual(fu.bucket_by_day(points, gauge=True), {dt.date(2026, 11, 18): 300})


class CostTests(SimpleTestCase):
    def test_free_quota_costs_nothing(self):
        self.assertEqual(fu.day_cost({'reads': 50_000, 'writes': 20_000, 'deletes': 20_000})['total'], 0)

    def test_usage_over_quota(self):
        cost = fu.day_cost({'reads': 150_000, 'writes': 120_000, 'deletes': 0})
        self.assertAlmostEqual(cost['reads'], 0.06)
        self.assertAlmostEqual(cost['writes'], 0.18)
        self.assertAlmostEqual(cost['total'], 0.24)

    def test_month_estimate_applies_monthly_quotas(self):
        rows = [{'reads': 0, 'writes': 0, 'deletes': 0, 'functions': 1_500_000,
                 'firestore_bytes': 3 * fu.GIB, 'storage_bytes': 0, 'egress_bytes': 0}] * 2
        est = fu.month_estimate(rows, days_in_month=30)
        # 3M calls - 2M free = 1M -> $0.40
        self.assertAlmostEqual(est['parts']['Cloud Functions calls'], 0.40)
        # (3 - 1) GiB * $0.18 * 2/30 of a month
        self.assertAlmostEqual(est['parts']['Firestore storage'], 2 * 0.18 * 2 / 30)

    def test_summary_shape(self):
        today = dt.date(2026, 11, 18)
        days = [today - dt.timedelta(days=1), today]
        usage = {'project': 'p', 'today': today, 'days': days,
                 'series': {'reads': {today: 60_000}, 'firestore_bytes': {today: 1024 ** 2}}}
        s = fu.build_summary(usage)
        self.assertEqual(s['today_row']['reads'], 60_000)
        self.assertAlmostEqual(s['month_usd'], 10_000 / 100_000 * 0.06)
        self.assertEqual(s['rows'][0]['date'], today)
        self.assertEqual(s['quotas'][0]['pct'], 100)

    def test_billing_table_name_validated(self):
        with self.assertRaises(fu.UsageUnavailable):
            fu.fetch_billing('bad name; DROP', 'p')


class PageTests(TestCase):
    def test_requires_admin(self):
        resp = self.client.get(reverse('firebase_usage'))
        self.assertEqual(resp.status_code, 302)

    def test_renders_with_usage_and_error(self):
        session = self.client.session
        session['admin'] = True
        session.save()
        today = dt.date(2026, 11, 18)
        summary = fu.build_summary({'project': 'p', 'today': today, 'days': [today], 'series': {}})
        summary['loaded_at'] = dt.datetime.now(dt.timezone.utc)
        with mock.patch.object(fu, 'get_usage_summary', return_value=summary), \
                mock.patch.object(fu, 'billing_table', return_value=''):
            resp = self.client.get(reverse('firebase_usage'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Estimated cost this month')
        self.assertContains(resp, 'turn on the billing export')

        with mock.patch.object(fu, 'get_usage_summary', side_effect=fu.UsageUnavailable('nope')):
            resp = self.client.get(reverse('firebase_usage'))
        self.assertContains(resp, 'nope')
