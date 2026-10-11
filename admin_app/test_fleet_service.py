"""Fleet plan prices and subscription rules shared with the mobile app."""

from datetime import datetime, timedelta, timezone

from django.test import SimpleTestCase

from admin_app.fleet_service import (
    FLEET_PLANS,
    FleetDateError,
    FleetProfileError,
    UnknownFleetPlan,
    activation_update,
    company_update,
    extension_update,
    fleets_to_csv,
    is_subscription_active,
    is_subscription_scheduled,
    parse_model_window,
    status_label,
)


class FleetPlanTests(SimpleTestCase):
    def test_prices_and_limits_match_mobile(self):
        self.assertEqual(FLEET_PLANS['starter'], {
            'name': 'Starter',
            'monthly': 999,
            'yearly': 9999,
            'vehicleLimit': 10,
            'driverLimit': 10,
        })
        self.assertEqual(FLEET_PLANS['business']['monthly'], 2999)
        self.assertEqual(FLEET_PLANS['business']['yearly'], 29999)
        self.assertEqual(FLEET_PLANS['business']['vehicleLimit'], 50)
        self.assertEqual(FLEET_PLANS['enterprise']['monthly'], 7999)
        self.assertEqual(FLEET_PLANS['enterprise']['yearly'], 79999)
        self.assertEqual(FLEET_PLANS['enterprise']['vehicleLimit'], 200)
        self.assertEqual(FLEET_PLANS['enterprise']['driverLimit'], 200)


class FleetSubscriptionRuleTests(SimpleTestCase):
    def test_active_and_trialing_with_future_or_open_expiry(self):
        future = datetime.now(timezone.utc) + timedelta(days=2)
        self.assertTrue(is_subscription_active({
            'subscriptionStatus': 'active',
            'subscriptionExpiresAt': future,
        }))
        self.assertTrue(is_subscription_active({
            'subscriptionStatus': 'trialing',
            'subscriptionExpiresAt': None,
        }))

    def test_expired_cancelled_and_past_due_are_inactive(self):
        past = datetime.now(timezone.utc) - timedelta(minutes=1)
        self.assertFalse(is_subscription_active({
            'subscriptionStatus': 'active',
            'subscriptionExpiresAt': past,
        }))
        self.assertFalse(is_subscription_active({
            'subscriptionStatus': 'cancelled',
            'subscriptionExpiresAt': datetime.now(timezone.utc) + timedelta(days=10),
        }))
        self.assertFalse(is_subscription_active({
            'subscriptionStatus': 'past_due',
        }))
        self.assertFalse(is_subscription_active({
            'subscriptionStatus': 'none',
        }))

    def test_future_start_is_scheduled_not_active(self):
        start = datetime.now(timezone.utc) + timedelta(days=3)
        end = start + timedelta(days=30)
        fleet = {
            'subscriptionStatus': 'active',
            'subscriptionStartsAt': start,
            'subscriptionExpiresAt': end,
        }
        self.assertTrue(is_subscription_scheduled(fleet))
        self.assertFalse(is_subscription_active(fleet))
        self.assertEqual(status_label(fleet), 'Scheduled')

    def test_status_label_uses_expiry(self):
        past = datetime.now(timezone.utc) - timedelta(days=1)
        self.assertEqual(status_label({
            'subscriptionStatus': 'active',
            'subscriptionExpiresAt': past,
        }), 'Expired')
        self.assertEqual(status_label({
            'subscriptionStatus': 'trialing',
        }), 'Trialing')
        self.assertEqual(status_label({
            'subscriptionStatus': 'cancelled',
        }), 'Cancelled')


class FleetActivationTests(SimpleTestCase):
    def test_activate_sets_limits_and_future_expiry(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        monthly = activation_update('starter', 'monthly', now=now)
        self.assertEqual(monthly['planId'], 'starter')
        self.assertEqual(monthly['billingCycle'], 'monthly')
        self.assertEqual(monthly['subscriptionStatus'], 'active')
        self.assertEqual(monthly['vehicleLimit'], 10)
        self.assertEqual(monthly['driverLimit'], 10)
        self.assertEqual(monthly['subscriptionExpiresAt'], now + timedelta(days=30))

        yearly = activation_update('enterprise', 'yearly', now=now)
        self.assertEqual(yearly['vehicleLimit'], 200)
        self.assertEqual(yearly['driverLimit'], 200)
        self.assertEqual(yearly['subscriptionExpiresAt'], now + timedelta(days=365))

    def test_future_start_and_custom_end_are_kept(self):
        now = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)
        window = parse_model_window(
            '2026-02-01',
            '2026-03-15',
            billing_cycle='monthly',
            now=now,
        )
        self.assertTrue(window['scheduled'])
        self.assertEqual(window['subscriptionStartsAt'], datetime(2026, 2, 1, tzinfo=timezone.utc))
        self.assertEqual(
            window['subscriptionExpiresAt'],
            datetime(2026, 3, 15, 23, 59, 59, tzinfo=timezone.utc),
        )
        saved = activation_update(
            'business',
            'monthly',
            now=now,
            starts_at=window['subscriptionStartsAt'],
            expires_at=window['subscriptionExpiresAt'],
        )
        self.assertEqual(saved['subscriptionStartsAt'], window['subscriptionStartsAt'])
        self.assertEqual(saved['subscriptionExpiresAt'], window['subscriptionExpiresAt'])
        self.assertEqual(saved['vehicleLimit'], 50)

    def test_blank_dates_start_now(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        window = parse_model_window('', '', billing_cycle='yearly', now=now)
        self.assertFalse(window['scheduled'])
        self.assertEqual(window['subscriptionStartsAt'], now)
        self.assertEqual(window['subscriptionExpiresAt'], now + timedelta(days=365))

    def test_end_before_start_is_rejected(self):
        now = datetime(2026, 1, 10, tzinfo=timezone.utc)
        with self.assertRaises(FleetDateError):
            parse_model_window('2026-02-01', '2026-01-01', billing_cycle='monthly', now=now)

    def test_extend_from_future_expiry_keeps_the_plan(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = datetime(2026, 2, 1, tzinfo=timezone.utc)
        updated = extension_update({
            'planId': 'business',
            'subscriptionExpiresAt': end,
        }, 30, now=now)
        self.assertEqual(updated['subscriptionExpiresAt'], end + timedelta(days=30))
        self.assertEqual(updated['subscriptionStatus'], 'active')
        self.assertNotIn('planId', updated)

    def test_extend_from_now_when_already_ended(self):
        now = datetime(2026, 3, 1, tzinfo=timezone.utc)
        updated = extension_update({
            'subscriptionExpiresAt': datetime(2026, 1, 1, tzinfo=timezone.utc),
        }, 365, now=now)
        self.assertEqual(updated['subscriptionExpiresAt'], now + timedelta(days=365))

    def test_extend_rejects_other_day_counts(self):
        with self.assertRaises(FleetDateError):
            extension_update({}, 7)

    def test_company_name_is_required_and_gstin_is_uppercased(self):
        saved = company_update('  Kerala Cabs ', '32abcde1234f1z5', '  Kochi ')
        self.assertEqual(saved['name'], 'Kerala Cabs')
        self.assertEqual(saved['gstin'], '32ABCDE1234F1Z5')
        self.assertEqual(saved['city'], 'Kochi')
        blank = company_update('Fleet', '  ', '')
        self.assertIsNone(blank['gstin'])
        self.assertIsNone(blank['city'])
        with self.assertRaises(FleetProfileError):
            company_update('A')

    def test_unknown_plan_is_rejected(self):
        with self.assertRaises(UnknownFleetPlan):
            activation_update('gold', 'monthly')

    def test_csv_includes_plan_and_status(self):
        text = fleets_to_csv([{
            'id': 'f1',
            'name': 'Kerala Cabs',
            'gstin': '32ABCDE1234F1Z5',
            'city': 'Kochi',
            'ownerId': 'uid-1',
            'planId': 'business',
            'billingCycle': 'yearly',
            'priceRupees': 29999,
            'subscriptionStatus': 'active',
            'statusLabel': 'Active',
            'isActive': True,
            'expiresAt': datetime(2026, 6, 1, tzinfo=timezone.utc),
            'vehicleLimit': 50,
            'driverLimit': 50,
            'razorpayPaymentId': 'pay_1',
            'razorpayOrderId': 'order_1',
        }])
        self.assertIn('planId', text)
        self.assertIn('business', text)
        self.assertIn('Kerala Cabs', text)
        self.assertIn('pay_1', text)
