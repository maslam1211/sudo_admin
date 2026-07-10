"""
Website Buy Now / checkout — same order + Razorpay flow as the mobile app.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone

from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from firebase_admin import firestore

from .razorpay_service import (
    create_razorpay_order,
    get_razorpay_credentials,
    verify_razorpay_payment,
)

logger = logging.getLogger(__name__)

# Single product sold on the website (matches primary mobile sticker SKU)
QR_PRODUCTS = {
    'sticker': {
        'key': 'sticker',
        'name': 'SudoTag QR',
        'price': 1.0,
        'description': (
            'Official windshield QR tag — scan to contact the vehicle owner '
            'securely for parking, alerts, and emergencies.'
        ),
    },
}
DEFAULT_PRODUCT_KEY = 'sticker'
SHIPPING_CHARGE = 0.0

# Prefer letter-leading names (mirrors mobile ValidationUtils.validateName)
NAME_LETTER_RE = re.compile(r"^[^\W\d_]([^\W\d_]|[\s'.-]){1,49}$", re.UNICODE)
MOBILE_RE = re.compile(r'^\d{10}$')
PINCODE_RE = re.compile(r'^[1-9][0-9]{5}$')
EMAIL_RE = re.compile(r'^[a-zA-Z0-9._%+-]+@(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}$')


def _get_db():
    from .views import db
    return db


def _json_body(request):
    if not request.body:
        return {}
    try:
        return json.loads(request.body.decode('utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def _err(message, status=400, **extra):
    payload = {'success': False, 'error': message}
    payload.update(extra)
    return JsonResponse(payload, status=status)


def _validate_checkout_payload(data: dict):
    errors = {}

    full_name = (data.get('fullName') or '').strip()
    if not full_name or len(full_name) < 2 or len(full_name) > 50 or not NAME_LETTER_RE.match(full_name):
        errors['fullName'] = (
            "Please enter a valid name (2–50 characters: letters, spaces, and .'- allowed)."
        )

    mobile = (data.get('mobile') or data.get('mobileNumber') or '').strip()
    mobile = re.sub(r'\D', '', mobile)
    if mobile.startswith('91') and len(mobile) == 12:
        mobile = mobile[2:]
    if not MOBILE_RE.match(mobile):
        errors['mobile'] = 'Please enter a valid 10-digit mobile number'

    email = (data.get('email') or data.get('emailAddress') or '').strip()
    if email and not EMAIL_RE.match(email):
        errors['email'] = 'Please enter a valid email address.'

    house_number = (data.get('houseNumber') or '').strip()
    street = (data.get('street') or data.get('address') or '').strip()
    if not house_number:
        errors['houseNumber'] = 'Please fill this required field'
    if not street:
        errors['street'] = 'Please fill this required field'

    city = (data.get('city') or data.get('district') or '').strip()
    state = (data.get('state') or '').strip()
    pincode = (data.get('pincode') or data.get('pinCode') or '').strip()
    if not city:
        errors['city'] = 'Please enter district/city'
    if not state:
        errors['state'] = 'Please enter state'
    if not PINCODE_RE.match(pincode):
        errors['pincode'] = 'Please enter a valid pincode'

    product_key = (data.get('selectedItem') or data.get('productKey') or DEFAULT_PRODUCT_KEY).strip()
    # Website sells a single SKU — coerce legacy keys to the official product
    if product_key not in QR_PRODUCTS:
        product_key = DEFAULT_PRODUCT_KEY

    try:
        quantity = int(data.get('quantity') or 1)
    except (TypeError, ValueError):
        quantity = 0
    if quantity < 1 or quantity > 20:
        errors['quantity'] = 'Quantity must be between 1 and 20'

    if errors:
        return None, errors

    product = QR_PRODUCTS[product_key]
    subtotal = product['price'] * quantity
    total = subtotal + SHIPPING_CHARGE
    post_office = (data.get('postOffice') or '').strip()
    landmark = (data.get('landmark') or '').strip() or None
    country = (data.get('country') or 'India').strip() or 'India'
    vehicle_number = (data.get('vehicleNumber') or '').strip() or 'N/A'
    vehicle_category = (data.get('vehicleCategory') or 'Website').strip() or 'Website'

    cleaned = {
        'fullName': full_name,
        'mobile': mobile,
        'email': email,
        'selectedItem': product_key,
        'selectedItemName': product['name'],
        'quantity': quantity,
        'unitPrice': product['price'],
        'subtotal': subtotal,
        'shipping': SHIPPING_CHARGE,
        'amount': total,
        'vehicleCategory': vehicle_category,
        'vehicleNumber': vehicle_number,
        'address': {
            'fullName': full_name,
            'mobileNumber': mobile,
            'houseNumber': house_number,
            'street': street,
            'postOffice': post_office,
            'landmark': landmark,
            'area': (data.get('area') or '').strip() or None,
            'address': street,
            'city': city,
            'state': state,
            'pincode': pincode,
            'country': country,
        },
    }
    return cleaned, None


@require_GET
def buy_now(request):
    """Checkout page — single SudoTag QR product + Razorpay checkout."""
    try:
        key_id, _ = get_razorpay_credentials()
    except RuntimeError:
        key_id = ''

    product = QR_PRODUCTS[DEFAULT_PRODUCT_KEY]
    return render(
        request,
        'buy.html',
        {
            'product': product,
            'shipping_charge': SHIPPING_CHARGE,
            'unit_total': product['price'] + SHIPPING_CHARGE,
            'razorpay_key_id': key_id,
            'create_order_url': reverse('checkout_create_order'),
            'verify_payment_url': reverse('checkout_verify_payment'),
            'success_url': reverse('buy_success'),
            'failure_url': reverse('buy_failure'),
            'cancelled_url': reverse('buy_cancelled'),
            'pending_url': reverse('buy_pending'),
        },
    )


@require_GET
def buy_success(request):
    """Detailed payment success / receipt page."""
    return render(
        request,
        'buy_success.html',
        {
            'order_id': request.GET.get('orderId', ''),
            'payment_id': request.GET.get('paymentId', ''),
            'razorpay_order_id': request.GET.get('razorpayOrderId', ''),
            'amount': request.GET.get('amount', ''),
            'product_name': request.GET.get('product', '') or QR_PRODUCTS[DEFAULT_PRODUCT_KEY]['name'],
            'quantity': request.GET.get('quantity', '1'),
            'customer_name': request.GET.get('name', ''),
            'customer_mobile': request.GET.get('mobile', ''),
            'customer_email': request.GET.get('email', ''),
            'delivery_address': request.GET.get('address', ''),
        },
    )


@require_GET
def buy_failure(request):
    """Detailed payment failure page."""
    return render(
        request,
        'buy_failure.html',
        {
            'reason': request.GET.get(
                'reason',
                'We couldn’t complete this payment. Check your connection and payment method, then try again.',
            ),
            'error_code': request.GET.get('code', ''),
            'order_id': request.GET.get('orderId', ''),
            'payment_id': request.GET.get('paymentId', ''),
            'amount': request.GET.get('amount', ''),
        },
    )


@require_GET
def buy_cancelled(request):
    """Payment cancelled by the user (Razorpay modal dismissed)."""
    return render(
        request,
        'buy_cancelled.html',
        {
            'reason': request.GET.get(
                'reason',
                'You closed the payment window before completing the payment. No money was charged.',
            ),
            'amount': request.GET.get('amount', ''),
        },
    )


@require_GET
def buy_pending(request):
    """Shown while payment verification is in progress (optional interstitial)."""
    return render(
        request,
        'buy_pending.html',
        {
            'payment_id': request.GET.get('paymentId', ''),
            'order_id': request.GET.get('orderId', ''),
        },
    )


@csrf_exempt
@require_POST
def checkout_create_order(request):
    """
    Create Firestore order + Razorpay order (mobile placeOrder steps 1–2).
    """
    data = _json_body(request)
    if data is None:
        return _err('Invalid JSON body')

    cleaned, errors = _validate_checkout_payload(data)
    if errors:
        return _err('Please fix the highlighted fields', fields=errors)

    try:
        key_id, _ = get_razorpay_credentials()
    except RuntimeError as exc:
        logger.error('%s', exc)
        return _err('Payment gateway is not configured', status=503)

    db = _get_db()
    web_user_id = f"web_{uuid.uuid4().hex[:16]}"
    now = datetime.now(timezone.utc)

    order_doc = {
        'fullName': cleaned['fullName'],
        'vehicleCategory': cleaned['vehicleCategory'],
        'vehicleNumber': cleaned['vehicleNumber'],
        'userId': web_user_id,
        'vehicleId': 'web',
        'mobile': cleaned['mobile'],
        'selectedItem': cleaned['selectedItem'],
        'quantity': cleaned['quantity'],
        'amount': cleaned['amount'],
        'qrId': '',
        'paymentStatus': 'pending',
        'paymentOrderId': None,
        'paymentId': None,
        'timestamp': now,
        'orderStatus': 1,  # Processing — same as mobile QrOrderCubit
        'address': cleaned['address'],
        'source': 'website',
        'shippingCharge': cleaned['shipping'],
        'unitPrice': cleaned['unitPrice'],
    }
    if cleaned['email']:
        order_doc['email'] = cleaned['email']

    try:
        # Step 1: create Firestore order (OrderRepository.createOrder)
        order_ref = db.collection('orders').document()
        order_ref.set(order_doc)
        firestore_order_id = order_ref.id

        # Step 2: create Razorpay order (Cloud Function createOrder)
        amount_paise = int(round(cleaned['amount'] * 100))
        rp_order = create_razorpay_order(
            amount_paise=amount_paise,
            user_id=web_user_id,
        )
        payment_order_id = rp_order['id']

        order_ref.update({
            'paymentOrderId': payment_order_id,
            'updatedAt': firestore.SERVER_TIMESTAMP,
        })
    except Exception as exc:
        logger.exception('checkout_create_order failed: %s', exc)
        return _err(f'Failed to create order: {exc}', status=500)

    return JsonResponse({
        'success': True,
        'orderId': firestore_order_id,
        'razorpayOrderId': payment_order_id,
        'amount': cleaned['amount'],
        'amountPaise': amount_paise,
        'currency': 'INR',
        'key': key_id,
        'customer': {
            'name': cleaned['fullName'],
            'contact': cleaned['mobile'],
            'email': cleaned['email'] or None,
        },
        'product': {
            'key': cleaned['selectedItem'],
            'name': cleaned['selectedItemName'],
            'quantity': cleaned['quantity'],
        },
        'shipping': cleaned['shipping'],
    })


@csrf_exempt
@require_POST
def checkout_verify_payment(request):
    """
    Verify Razorpay payment and mark order paid (mobile placeOrder steps 4–5
    + Cloud Function verifyPayment side effects).
    """
    data = _json_body(request)
    if data is None:
        return _err('Invalid JSON body')

    firestore_order_id = (data.get('orderId') or '').strip()
    razorpay_order_id = (data.get('razorpayOrderId') or data.get('paymentOrderId') or '').strip()
    razorpay_payment_id = (data.get('razorpayPaymentId') or data.get('paymentId') or '').strip()
    razorpay_signature = (data.get('razorpaySignature') or data.get('signature') or '').strip()

    if not razorpay_order_id or not razorpay_payment_id:
        return _err(
            'Missing required payment verification parameters (orderId and paymentId)'
        )

    try:
        result = verify_razorpay_payment(
            razorpay_order_id=razorpay_order_id,
            razorpay_payment_id=razorpay_payment_id,
            razorpay_signature=razorpay_signature or None,
        )
    except Exception as exc:
        logger.exception('verify payment error: %s', exc)
        return _err(f'Payment verification failed: {exc}', status=500)

    if not result.get('verified'):
        return JsonResponse({
            'success': False,
            'verified': False,
            'error': result.get('reason') or 'Payment verification failed.',
        }, status=400)

    db = _get_db()
    actual_order_id = result.get('actualOrderId') or razorpay_order_id
    verification_method = result.get('verificationMethod') or (
        'signature' if razorpay_signature else 'api'
    )

    # Resolve + update order first so payment.userId matches the order
    order_doc = None
    order_ref = None
    try:
        if firestore_order_id:
            candidate = db.collection('orders').document(firestore_order_id)
            snap = candidate.get()
            if snap.exists:
                order_ref = candidate
                order_doc = snap.to_dict() or {}

        if order_doc is None:
            docs = list(
                db.collection('orders')
                .where('paymentOrderId', '==', razorpay_order_id)
                .limit(1)
                .stream()
            )
            if not docs and actual_order_id != razorpay_order_id:
                docs = list(
                    db.collection('orders')
                    .where('paymentOrderId', '==', actual_order_id)
                    .limit(1)
                    .stream()
                )
            if docs:
                order_ref = docs[0].reference
                order_doc = docs[0].to_dict() or {}
                firestore_order_id = docs[0].id

        if order_ref is not None:
            update_payload = {
                'paymentId': razorpay_payment_id,
                'paymentOrderId': razorpay_order_id,
                'paymentStatus': 'paid',
                'paymentVerified': True,
                'paymentVerifiedAt': firestore.SERVER_TIMESTAMP,
                'updatedAt': firestore.SERVER_TIMESTAMP,
            }
            if razorpay_signature:
                update_payload['razorpaySignature'] = razorpay_signature
            order_ref.update(update_payload)
            order_doc = {**(order_doc or {}), **update_payload}
        else:
            logger.warning(
                'No order found for paymentOrderId=%s firestoreId=%s',
                razorpay_order_id,
                firestore_order_id,
            )
    except Exception as order_update_error:
        logger.exception('Error updating order status: %s', order_update_error)

    payment_record = {
        'orderId': razorpay_order_id,
        'paymentId': razorpay_payment_id,
        'signature': razorpay_signature or None,
        'userId': (order_doc or {}).get('userId') or 'web_guest',
        'verified': True,
        'verifiedAt': firestore.SERVER_TIMESTAMP,
        'verificationMethod': verification_method,
        'timestamp': firestore.SERVER_TIMESTAMP,
        'source': 'website',
        'firestoreOrderId': firestore_order_id or None,
    }
    if actual_order_id != razorpay_order_id:
        payment_record['actualOrderId'] = actual_order_id

    try:
        db.collection('payments').add(payment_record)
    except Exception as firestore_error:
        logger.error('Error storing payment record: %s', firestore_error)

    amount = None
    product_name = ''
    if order_doc:
        amount = order_doc.get('amount')
        selected = order_doc.get('selectedItem')
        if selected in QR_PRODUCTS:
            product_name = QR_PRODUCTS[selected]['name']

    # Match mobile confirmation response shape
    return JsonResponse({
        'success': True,
        'verified': True,
        'orderId': firestore_order_id or razorpay_order_id,
        'paymentId': razorpay_payment_id,
        'razorpayOrderId': razorpay_order_id,
        'signature': razorpay_signature or None,
        'amount': amount,
        'productName': product_name,
        'paymentStatus': 'paid',
    })
