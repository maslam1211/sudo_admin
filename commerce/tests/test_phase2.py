"""Phase 2: app config + checkout on PostgreSQL."""

from __future__ import annotations

import hashlib
import hmac
import io
import json
from datetime import datetime, timedelta, timezone
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import Client, TestCase, override_settings

from api.tests.fakes import FakeDB
from appconfig import service as appconfig_service
from appconfig.models import AppConfig, AppUpdateEvent
from commerce import pricing, razorpay_guard, service, sync
from commerce.models import MASTER_FIRESTORE, MASTER_POSTGRES, Coupon, Order, Payment, PaymentClaim

NOW = datetime(2026, 11, 28, 10, 0, tzinfo=timezone.utc)
ADDRESS = {'fullName': 'Asha', 'mobileNumber': '9876543210', 'houseNumber': '12', 'street': 'MG Road',
           'city': 'Kochi', 'state': 'Kerala', 'pincode': '682001', 'country': 'India', 'address': 'Near park'}


# ─── pricing parity (functions/checkout_coupons.js) ──────────────────────────
class PricingTests(TestCase):
    def test_round2_matches_js_math_round_not_bankers(self):
        self.assertEqual(pricing.round2(0.125), 0.13)      # Python round() gives 0.12
        self.assertEqual(pricing.round2(2.675), 2.68)      # binary representation: 2.675 → 268
        self.assertEqual(pricing.round2('12.345'), 12.35)
        self.assertEqual(pricing.round2('abc'), 0)

    def test_quantity_parse_int_and_clamp(self):
        self.assertEqual([pricing.normalize_quantity(q) for q in (None, 'x', 0, '4.9', 21, -3, '3')],
                         [1, 1, 1, 4, 20, 1, 3])

    def test_unit_price_keys_and_tag_models(self):
        settings = {'stickerUnitPrice': 250, 'shippingCharge': 0, 'smartPrice': '399'}
        self.assertEqual(pricing.unit_and_shipping(settings), (250, 0))
        self.assertEqual(pricing.unit_and_shipping({}), (199, 49))
        self.assertEqual(pricing.tag_price(settings, 'smart', 250), 399)
        self.assertEqual(pricing.tag_price(settings, 'pro', 250), 699)
        self.assertEqual(pricing.tag_price({'litePrice': 150}, 'lite', 199), 150)
        self.assertIsNone(pricing.tag_price(settings, 'unknown', 250))

    def test_coupon_kinds(self):
        q = lambda coupon: pricing.compute_coupon_discount(unit_price=199, quantity=2, shipping=49, coupon=coupon)
        self.assertEqual(q(None)['total'], 447)
        self.assertEqual(q({'discountType': 'percent', 'discountValue': 15})['total'], 387.3)
        self.assertEqual(q({'discountType': 'fixed', 'discountValue': 500})['subtotal'], 0)
        self.assertEqual(q({'discountType': 'unit_price', 'discountValue': 99})['subtotal'], 198)

    def test_validity_messages(self):
        base = {'active': True, 'discountType': 'percent', 'discountValue': 10}
        self.assertEqual(pricing.coupon_validity_error({**base, 'active': False}, 1), 'This coupon code is not active.')
        self.assertEqual(pricing.coupon_validity_error({**base, 'expiresAt': NOW}, 1, NOW), 'This coupon code has expired.')
        self.assertEqual(pricing.coupon_validity_error({**base, 'minQuantity': 2}, 1), 'This coupon requires at least 2 items.')
        self.assertEqual(pricing.coupon_validity_error({**base, 'maxUses': 3, 'usedCount': 3}, 1),
                         'This coupon code has reached its usage limit.')
        self.assertIsNone(pricing.coupon_validity_error(base, 1))


# ─── shared API test setup ───────────────────────────────────────────────────
def _verify(token):
    if token.startswith('good-'):
        return {'uid': token[5:], 'phone_number': ''}
    raise ValueError('bad')


def fake_claim(db, ref, purpose, uid):
    snap = ref.get()
    if snap.exists and (snap.to_dict() or {}).get('purpose') != purpose:
        raise razorpay_guard.PaymentRejected('This payment has already been used.')
    if not snap.exists:
        ref.set({'purpose': purpose, 'uid': uid})


class Base(TestCase):
    def setUp(self):
        self.db = FakeDB()
        self.db.put('web_checkout_settings/default', {'sudoTagPrice': 199, 'shippingCharge': 49, 'smartPrice': 349})
        self.db.put('vehicles/v1', {'ownerId': 'u1', 'registrationNumber': 'KL07AB1234', 'vehicleType': 'car'})
        self.db.put('web_coupons/SAVE10', {'code': 'SAVE10', 'active': True, 'discountType': 'percent',
                                           'discountValue': 10, 'usedCount': 0})
        self.rp_orders = []
        self.payments = {}
        for p in (
            mock.patch('api.firebase.verify_id_token', side_effect=_verify),
            mock.patch('api.firebase.firestore_db', return_value=self.db),
            mock.patch('commerce.razorpay_guard.create_order', side_effect=self._create_rp_order),
            mock.patch('commerce.razorpay_guard.fetch_payment', side_effect=lambda pid: self.payments.get(pid, {})),
            mock.patch('commerce.razorpay_guard.fetch_order', side_effect=self._fetch_rp_order),
            mock.patch('commerce.razorpay_guard._claim_in_firestore', side_effect=fake_claim),
            mock.patch('commerce.razorpay_guard.signature_matches', side_effect=lambda o, p, s: s == f'sig-{o}-{p}'),
        ):
            p.start()
            self.addCleanup(p.stop)
        sync.import_everything(self.db)
        self.client = Client()

    def _create_rp_order(self, *, amount_paise, receipt, notes):
        order = {'id': f'order_rp{len(self.rp_orders) + 1}', 'amount': amount_paise, 'notes': notes}
        self.rp_orders.append(order)
        return order

    def _fetch_rp_order(self, order_id):
        for order in self.rp_orders:
            if order['id'] == order_id:
                return order
        return {}

    def call(self, method, path, body=None, uid='u1', **extra):
        if uid:
            extra['HTTP_AUTHORIZATION'] = f'Bearer good-{uid}'
        if method == 'get':
            return self.client.get(path, **extra)
        return getattr(self.client, method)(path, data=json.dumps(body or {}),
                                            content_type='application/json', **extra)

    def place(self, **overrides):
        body = {'vehicleId': 'v1', 'selectedItem': 'smart', 'quantity': 2, 'address': ADDRESS,
                'mobile': '9876543210', 'fullName': 'Asha', 'amount': 1, **overrides}
        return self.call('post', '/api/v1/orders', body)

    def pay(self, order_id, amount_paise, payment_id='pay_1', uid='u1', rp_order_id=None, **extra_payment):
        order = Order.objects.get(id=order_id)
        self.payments[payment_id] = {'id': payment_id, 'status': 'captured', 'currency': 'INR',
                                     'amount': amount_paise, 'order_id': rp_order_id or order.razorpay_order_id,
                                     **extra_payment}
        return self.call('post', f'/api/v1/orders/{order_id}/payment', {'razorpayPaymentId': payment_id}, uid=uid)


# ─── orders through the API ──────────────────────────────────────────────────
class OrderApiTests(Base):
    def test_server_prices_the_order_and_ignores_client_amount(self):
        r = self.place(couponCode='save10', partnerCode='p-abc')
        self.assertEqual(r.status_code, 201, r.content)
        body = r.json()
        # smart 349 x2 = 698, -10% = 628.2, + 49 shipping
        self.assertEqual(body['quote']['total'], 677.2)
        self.assertEqual(body['amountPaise'], 67720)
        self.assertEqual(self.rp_orders[0]['amount'], 67720)
        self.assertEqual(self.rp_orders[0]['notes']['quantity'], 2)
        order = Order.objects.get(id=body['order']['id'])
        self.assertEqual((order.master, order.user_id, order.payment_status, order.order_status),
                         (MASTER_POSTGRES, 'u1', 'pending', 1))
        projected = self.db.docs[f'orders/{order.id}']
        self.assertEqual(projected['origin'], 'api')
        self.assertEqual(projected['amount'], 677.2)
        self.assertEqual(projected['partnerCode'], 'P-ABC')
        self.assertEqual(projected['paymentOrderId'], 'order_rp1')
        self.assertEqual(projected['coupon']['code'], 'SAVE10')

    def test_needs_sign_in_and_own_vehicle(self):
        self.assertEqual(self.place().status_code, 201)
        self.assertEqual(self.call('post', '/api/v1/orders', {'vehicleId': 'v1'}, uid=None).status_code, 401)
        r = self.call('post', '/api/v1/orders', {'vehicleId': 'v1', 'address': ADDRESS}, uid='stranger')
        self.assertEqual(r.status_code, 403)

    def test_buying_closed_message(self):
        self.db.put('web_checkout_settings/default', {'buyingOpen': False, 'buyingClosedMessage': 'Back next week'})
        sync.import_settings(self.db)
        r = self.place()
        self.assertEqual(r.json()['error']['message'], 'Back next week')

    def test_invalid_coupon_and_address(self):
        self.assertEqual(self.place(couponCode='NOPE')['error'] if False else
                         self.place(couponCode='NOPE').json()['error']['message'], 'Invalid coupon code.')
        self.assertEqual(self.place(address={'city': 'x'}).status_code, 400)

    def test_payment_marks_paid_records_payment_and_coupon_once(self):
        order_id = self.place(couponCode='SAVE10').json()['order']['id']
        r = self.pay(order_id, 67720)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()['verified'])
        order = Order.objects.get(id=order_id)
        self.assertTrue(order.payment_verified)
        self.assertEqual(order.payment_status, 'paid')
        fs = self.db.docs[f'orders/{order_id}']
        self.assertTrue(fs['paymentVerified'])            # what the partner-commission trigger reads
        self.assertEqual(fs['paymentStatus'], 'paid')
        self.assertEqual(Payment.objects.get(id='pay_1').amount_paise, 67720)
        self.assertIn('payments/pay_1', self.db.docs)
        self.assertEqual(self.db.docs['payment_claims/pay_1']['purpose'], f'order:{order.razorpay_order_id}')
        self.assertEqual(self.db.docs['web_coupons/SAVE10']['usedCount'], 1)
        self.assertEqual(Coupon.objects.get(code='SAVE10').used_count, 1)
        # Retry of the same payment: fine, no second coupon use.
        self.assertEqual(self.pay(order_id, 67720).status_code, 200)
        self.assertEqual(self.db.docs['web_coupons/SAVE10']['usedCount'], 1)

    def test_underpayment_is_rejected(self):
        order_id = self.place().json()['order']['id']
        r = self.pay(order_id, 100)
        self.assertEqual(r.status_code, 400)
        self.assertIn('amount', r.json()['error']['message'])
        self.assertFalse(Order.objects.get(id=order_id).payment_verified)

    def test_payment_for_another_razorpay_order_is_rejected(self):
        order_id = self.place().json()['order']['id']
        r = self.pay(order_id, 74700, rp_order_id='order_other')
        self.assertIn('different order', r.json()['error']['message'])

    def test_payment_already_claimed_by_cloud_function_is_rejected(self):
        order_id = self.place().json()['order']['id']
        self.db.put('payment_claims/pay_1', {'purpose': 'order:order_elsewhere'})
        r = self.pay(order_id, 74700)
        self.assertEqual(r.json()['error']['message'], 'This payment has already been used.')

    def test_bad_signature_is_rejected(self):
        order_id = self.place().json()['order']['id']
        order = Order.objects.get(id=order_id)
        self.payments['pay_1'] = {'id': 'pay_1', 'status': 'captured', 'currency': 'INR', 'amount': 74700,
                                  'order_id': order.razorpay_order_id}
        r = self.call('post', f'/api/v1/orders/{order_id}/payment',
                      {'razorpayPaymentId': 'pay_1', 'razorpaySignature': 'forged'})
        self.assertIn('signature', r.json()['error']['message'])
        r = self.call('post', f'/api/v1/orders/{order_id}/payment',
                      {'razorpayPaymentId': 'pay_1', 'razorpaySignature': f'sig-{order.razorpay_order_id}-pay_1'})
        self.assertEqual(r.status_code, 200, r.content)

    def test_someone_elses_order_is_not_found(self):
        order_id = self.place().json()['order']['id']
        self.assertEqual(self.pay(order_id, 74700, uid='stranger').status_code, 404)

    def test_failed_and_cancel(self):
        order_id = self.place().json()['order']['id']
        r = self.call('post', f'/api/v1/orders/{order_id}/payment-failed')
        self.assertEqual(r.json()['order']['paymentStatus'], 'failed')
        r = self.call('post', f'/api/v1/orders/{order_id}/cancel')
        self.assertEqual(r.json()['order']['orderStatus'], 4)
        self.assertEqual(self.db.docs[f'orders/{order_id}']['orderStatus'], 4)
        self.assertEqual(self.call('post', f'/api/v1/orders/{order_id}/cancel').status_code, 400)

    def test_list_includes_orders_from_older_builds(self):
        self.place()
        self.db.put('orders/old1', {'userId': 'u1', 'amount': 199, 'paymentStatus': 'paid', 'orderStatus': 3,
                                    'timestamp': NOW - timedelta(days=3)})
        self.db.put('orders/notmine', {'userId': 'u2', 'amount': 199})
        sync.import_orders(self.db)
        ids = [o['id'] for o in self.call('get', '/api/v1/orders').json()['orders']]
        self.assertEqual(len(ids), 2)
        self.assertIn('old1', ids)
        self.assertNotIn('notmine', ids)

    def test_cancel_older_build_order_writes_firestore(self):
        self.db.put('orders/old1', {'userId': 'u1', 'amount': 199, 'orderStatus': 1})
        sync.import_orders(self.db)
        r = self.call('post', '/api/v1/orders/old1/cancel')
        self.assertEqual(r.json()['order']['orderStatus'], 4)
        self.assertEqual(self.db.docs['orders/old1']['orderStatus'], 4)
        self.assertEqual(Order.objects.get(id='old1').master, MASTER_FIRESTORE)


class QuoteAndOffersTests(Base):
    def test_quote_and_offers(self):
        r = self.call('post', '/api/v1/checkout/quote', {'couponCode': 'SAVE10', 'quantity': 1, 'productKey': 'smart'})
        self.assertEqual(r.json()['quote']['total'], 363.1)  # 349 - 34.9 + 49
        self.assertEqual(self.call('post', '/api/v1/checkout/quote', {'couponCode': 'X'}).status_code, 400)
        offers = self.call('get', '/api/v1/checkout/coupons').json()['coupons']
        self.assertEqual([o['code'] for o in offers], ['SAVE10'])

    def test_settings_are_public(self):
        body = self.client.get('/api/v1/checkout/settings').json()
        self.assertEqual((body['sudoTagPrice'], body['orderingOpen']), (199, True))


@override_settings(RAZORPAY_WEBHOOK_SECRET='whsec')
class WebhookTests(Base):
    def post_event(self, event, secret='whsec'):
        raw = json.dumps(event).encode()
        sig = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        return self.client.post('/api/v1/webhooks/razorpay', data=raw, content_type='application/json',
                                HTTP_X_RAZORPAY_SIGNATURE=sig)

    def test_signature_required(self):
        self.assertEqual(self.post_event({'event': 'payment.captured'}, secret='wrong').status_code, 401)

    def test_captured_payment_completes_order_when_app_never_returned(self):
        order_id = self.place().json()['order']['id']
        order = Order.objects.get(id=order_id)
        self.payments['pay_9'] = {'id': 'pay_9', 'status': 'captured', 'currency': 'INR', 'amount': 74700,
                                  'order_id': order.razorpay_order_id}
        event = {'event': 'payment.captured',
                 'payload': {'payment': {'entity': {'id': 'pay_9', 'order_id': order.razorpay_order_id}}}}
        self.assertEqual(self.post_event(event).json()['outcome'], 'paid')
        self.assertTrue(Order.objects.get(id=order_id).payment_verified)
        self.assertEqual(self.post_event(event).json()['outcome'], 'already-paid')

    def test_unknown_order_left_to_cloud_function(self):
        event = {'event': 'payment.captured', 'payload': {'payment': {'entity': {'id': 'p', 'order_id': 'o'}}}}
        self.assertEqual(self.post_event(event).json()['outcome'], 'unknown-order')


# ─── sync rules and admin hooks ──────────────────────────────────────────────
class SyncTests(Base):
    def test_import_never_overwrites_postgres_master(self):
        order_id = self.place().json()['order']['id']
        self.db.docs[f'orders/{order_id}']['amount'] = 1  # tampering in Firestore
        stats = sync.import_orders(self.db)
        self.assertEqual(stats['skipped_postgres_master'], 1)
        self.assertEqual(Order.objects.get(id=order_id).amount, 747)

    def test_deleted_firestore_orders_are_kept_and_marked(self):
        self.db.put('orders/old1', {'userId': 'u1', 'amount': 199})
        sync.import_orders(self.db)
        del self.db.docs['orders/old1']
        self.assertEqual(sync.import_orders(self.db)['marked_deleted'], 1)
        self.assertIsNotNone(Order.objects.get(id='old1').deleted_at)

    def test_admin_status_change_updates_postgres_and_projects(self):
        order_id = self.place().json()['order']['id']
        self.db.docs[f'orders/{order_id}']['orderStatus'] = 3   # admin panel's Firestore write
        service.admin_status_changed(self.db, order_id, 3)
        self.assertEqual(Order.objects.get(id=order_id).order_status, 3)
        self.assertEqual(self.db.docs[f'orders/{order_id}']['orderStatus'], 3)

    def test_failed_projection_is_retried(self):
        self.db.fail_writes = True
        r = self.place()
        order_id = r.json()['order']['id']
        self.assertNotIn(f'orders/{order_id}', self.db.docs)
        self.db.fail_writes = False
        self.assertEqual(sync.project_pending_orders(self.db), 1)
        self.assertIn(f'orders/{order_id}', self.db.docs)
        self.assertEqual(sync.project_pending_orders(self.db), 0)

    def test_admin_coupon_save_reaches_postgres_at_once(self):
        from admin_app import checkout_coupon_service as admin_coupons

        admin_coupons.save_coupon(self.db, {'code': 'new20', 'discountType': 'percent', 'discountValue': 20})
        self.assertEqual(Coupon.objects.get(code='NEW20').discount_value, 20)
        admin_coupons.delete_coupon(self.db, 'NEW20')
        self.assertIsNotNone(Coupon.objects.get(code='NEW20').deleted_at)

    def test_admin_orders_deleted_removes_projection(self):
        order_id = self.place().json()['order']['id']
        service.admin_orders_deleted(self.db, [order_id])
        sync.project_pending_orders(self.db)
        self.assertNotIn(f'orders/{order_id}', self.db.docs)
        self.assertIsNotNone(Order.objects.get(id=order_id).deleted_at)

    def test_claims_are_single_purpose_in_postgres_too(self):
        razorpay_guard.claim_payment(self.db, payment_id='p1', purpose='order:a')
        razorpay_guard.claim_payment(self.db, payment_id='p1', purpose='order:a')
        with self.assertRaises(razorpay_guard.PaymentRejected):
            razorpay_guard.claim_payment(self.db, payment_id='p1', purpose='fleet:x')
        self.assertEqual(PaymentClaim.objects.count(), 1)


class ReconcileTests(Base):
    def test_apply_then_reconcile_ok_and_detects_drift(self):
        self.db.put('orders/old1', {'userId': 'u1', 'amount': 199, 'timestamp': NOW})
        self.db.put('appConfig/android', {'latestBuild': 110, 'latestVersion': '1.1.59', 'publishedAt': NOW})
        self.db.put('appConfig/android/releases/r1', {'latestBuild': 110, 'publishedAt': NOW})
        self.place()
        out = io.StringIO()
        call_command('migrate_phase2', '--apply', stdout=out)
        self.assertIn('Reconcile OK', out.getvalue())
        self.db.docs['orders/old1']['amount'] = 299
        with self.assertRaises(CommandError):
            call_command('migrate_phase2', stdout=io.StringIO())


# ─── app config ──────────────────────────────────────────────────────────────
class AppConfigTests(Base):
    def test_public_config_from_postgres(self):
        self.assertEqual(self.client.get('/api/v1/app/config/android').json(), {'exists': False})
        self.db.put('appConfig/android', {'latestBuild': 110, 'latestVersion': '1.1.59', 'minSupportedBuild': 100,
                                          'forceUpdate': False, 'updateTitle': 'New', 'publishedAt': NOW})
        appconfig_service.import_config(self.db, 'android')
        body = self.client.get('/api/v1/app/config/android').json()
        self.assertEqual((body['exists'], body['latestBuild'], body['updateTitle']), (True, 110, 'New'))
        self.assertEqual(body['publishedAt'], NOW.isoformat())
        self.assertEqual(self.client.get('/api/v1/app/config/web').status_code, 400)

    def test_admin_get_config_reads_postgres_first(self):
        from admin_app import app_version_service as admin_versions

        self.db.put('appConfig/ios', {'latestBuild': 5})
        self.assertEqual(admin_versions.get_config(self.db, 'ios')['latestBuild'], 5)  # Firestore fallback
        appconfig_service.import_config(self.db, 'ios')
        self.db.docs['appConfig/ios']['latestBuild'] = 6
        self.assertEqual(admin_versions.get_config(self.db, 'ios')['latestBuild'], 5)  # PostgreSQL copy

    def test_update_events_api_and_import_from_older_builds(self):
        r = self.call('post', '/api/v1/app/update-events',
                      {'platform': 'ios', 'event': 'check_failed', 'version': '1.1.59', 'build': 110, 'error': 'x'})
        self.assertEqual(r.status_code, 201)
        self.db.put('app_update_events/e1', {'uid': 'u2', 'platform': 'android', 'event': 'play_no_update',
                                             'version': '1.1.50', 'build': 100, 'createdAt': NOW})
        self.assertEqual(appconfig_service.import_events(self.db), 1)
        self.assertEqual(appconfig_service.import_events(self.db), 0)
        self.assertEqual(AppUpdateEvent.objects.count(), 2)
        self.assertEqual(len(appconfig_service.recent_events(errors_only=True)), 1)
        self.assertEqual(self.call('post', '/api/v1/app/update-events', {'platform': 'ios'}, uid=None).status_code, 401)

    def test_report_app_version_writes_user_fields(self):
        self.db.put('users/u1', {'fullName': 'Asha'})
        r = self.call('put', '/api/v1/me/app-version', {'platform': 'android', 'version': '1.1.60', 'build': 111})
        self.assertEqual(r.status_code, 200)
        self.assertEqual((self.db.docs['users/u1']['appBuild'], self.db.docs['users/u1']['fullName']), (111, 'Asha'))


# ─── website checkout uses the same payment checks ───────────────────────────
class WebsiteVerifyTests(Base):
    def setUp(self):
        super().setUp()
        p = mock.patch('admin_app.checkout_views._get_db', return_value=self.db)
        p.start()
        self.addCleanup(p.stop)
        self.db.put('orders/web1', {'userId': 'web_x', 'amount': 846, 'paymentOrderId': 'order_w1',
                                    'paymentStatus': 'pending'})

    def verify(self, amount_paise, rp_order_amount=84600):
        self.payments['pay_w'] = {'id': 'pay_w', 'status': 'captured', 'currency': 'INR',
                                  'amount': amount_paise, 'order_id': 'order_w1'}
        with mock.patch('commerce.razorpay_guard.fetch_order', return_value={'id': 'order_w1', 'amount': rp_order_amount}):
            return self.client.post('/admin/api/checkout/verify-payment/', data=json.dumps(
                {'orderId': 'web1', 'razorpayOrderId': 'order_w1', 'razorpayPaymentId': 'pay_w'}),
                content_type='application/json')

    def test_underpayment_rejected(self):
        r = self.verify(100)
        self.assertEqual(r.status_code, 400)
        self.assertNotEqual(self.db.docs['orders/web1']['paymentStatus'], 'paid')

    def test_full_payment_accepted_and_claimed(self):
        r = self.verify(84600)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.db.docs['orders/web1']['paymentStatus'], 'paid')
        self.assertEqual(self.db.docs['payment_claims/pay_w']['purpose'], 'order:order_w1')
