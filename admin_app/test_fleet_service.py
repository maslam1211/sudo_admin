"""Fleet plan prices and subscription rules shared with the mobile app."""

from datetime import datetime, timedelta, timezone

from django.test import SimpleTestCase

from admin_app.fleet_service import (
    FLEET_PLANS,
    UnknownFleetPlan,
    activation_update,
    fleets_to_csv,
    is_subscription_active,
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
