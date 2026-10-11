"""Sudo admin wallet management.

Balance changes are ledger entries. The page never writes a raw balance total.
"""
from __future__ import annotations

import csv
import uuid

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods
from firebase_admin import firestore


def _require_admin(request):
    if not request.session.get('admin'):
        messages.error(request, 'Admin access required')
        return redirect('admin_login')
    return None


def _db():
    return firestore.client()


def _actor(request):
    return (request.session.get('user_id') or request.session.get('email') or 'django-admin')


def _stamp(value):
    if value is None:
        return ''
    iso = getattr(value, 'isoformat', None)
    return iso() if callable(iso) else str(value)


def _int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _resolve_uid(db, raw):
    text = (raw or '').strip()
    if not text:
        return ''
    if '@' in text:
        matches = list(
            db.collection('users').where('emailAddress', '==', text.lower()).limit(1).stream()
        )
        if not matches:
            matches = list(
                db.collection('users').where('emailAddress', '==', text).limit(1).stream()
            )
        return matches[0].id if matches else ''
    return text


def _tx_row(doc):
    data = doc.to_dict() or {}
    return {
        'id': doc.id,
        'type': data.get('type') or '',
        'points': data.get('points') or 0,
        'status': data.get('status') or '',
        'reason': data.get('reasonCode') or data.get('reason') or '',
        'report_id': data.get('reportId') or '',
        'redemption_id': data.get('redemptionId') or '',
        'related': data.get('relatedTransactionId') or '',
        'created': _stamp(data.get('createdAt')),
    }


def _load_wallet(db, uid):
    user = db.collection('users').document(uid).get()
    if not user.exists:
        return None, []
    data = user.to_dict() or {}
    lifetime = data.get('lifetimeRewardPoints')
    available = data.get('rewardBalance') or 0
    rows = [
        _tx_row(doc)
        for doc in (
            db.collection('users')
            .document(uid)
            .collection('reward_transactions')
            .order_by('createdAt', direction=firestore.Query.DESCENDING)
            .limit(40)
            .stream()
        )
    ]
    reversed_ids = set()
    for row in rows:
        if row['type'] == 'reversal' and row['related']:
            reversed_ids.add(row['related'])
        if row['id'].startswith('reversal_'):
            reversed_ids.add(row['id'][len('reversal_'):])
    for row in rows:
        row['can_reverse'] = row['type'] == 'credit' and row['id'] not in reversed_ids
    wallet = {
        'uid': uid,
        'name': data.get('fullName') or '',
        'email': data.get('emailAddress') or '',
        'available': available,
        'lifetime': available if lifetime is None else lifetime,
        'redeemed': data.get('redeemedRewardPoints') or 0,
        'updated': _stamp(data.get('walletUpdatedAt')),
    }
    return wallet, rows


def _load_reports(db, uid, status, category, vehicle_id):
    query = db.collection('issue_reports')
    if uid:
        query = query.where('reporterUid', '==', uid)
    elif status:
        query = query.where('status', '==', status)
    query = query.order_by('createdAt', direction=firestore.Query.DESCENDING).limit(80)
    reports = []
    for doc in query.stream():
        data = doc.to_dict() or {}
        if category and data.get('issueType') != category:
            continue
        if status and uid and data.get('status') != status:
            continue
        if vehicle_id and data.get('vehicleId') != vehicle_id:
            continue
        reports.append({
            'id': doc.id,
            'vehicle_id': data.get('vehicleId') or '',
            'reporter_uid': data.get('reporterUid') or '',
            'owner_uid': data.get('ownerUid') or '',
            'category': data.get('issueType') or '',
            'status': data.get('status') or '',
            'verification': data.get('verificationStatus') or '',
            'duplicate': data.get('verificationStatus') == 'duplicate',
            'points': data.get('rewardPoints') or 0,
            'created': _stamp(data.get('createdAt')),
        })
    return reports


def _load_redemptions(db, status):
    query = db.collection('reward_redemptions')
    if status == 'manually_redeemed':
        query = query.where('manualRedeemed', '==', True).limit(40)
    else:
        if status:
            query = query.where('status', '==', status)
        query = query.order_by('createdAt', direction=firestore.Query.DESCENDING).limit(40)
    rows = []
    for doc in query.stream():
        data = doc.to_dict() or {}
        current = data.get('status') or ''
        manual = data.get('manualRedeemed') is True
        rows.append({
            'id': doc.id,
            'uid': data.get('uid') or '',
            'reward_id': data.get('rewardId') or '',
            'points': data.get('pointsCost') or 0,
            'status': current,
            'label': 'Manually redeemed' if manual else current,
            'reason': data.get('rejectionReason') or '',
            'reference': data.get('fulfilmentReference') or '',
            'created': _stamp(data.get('createdAt')),
            'open': current in ('requested', 'processing'),
        })
    if status == 'manually_redeemed':
        rows.sort(key=lambda row: row['created'], reverse=True)
    return rows


def _load_catalog(db):
    rows = []
    for doc in db.collection('reward_catalog').limit(50).stream():
        data = doc.to_dict() or {}
        rows.append({
            'id': doc.id,
            'title': data.get('title') or '',
            'description': data.get('description') or '',
            'points_cost': data.get('pointsCost') or 0,
            'active': data.get('active') is True,
            'stock': '' if data.get('stock') is None else data.get('stock'),
            'terms': data.get('terms') or '',
            'reward_type': data.get('rewardType') or 'other',
        })
    return rows


def _page(request):
    tab = (request.GET.get('tab') or 'wallet').strip()
    if tab not in ('wallet', 'reports', 'redemptions', 'catalog'):
        tab = 'wallet'
    query = (request.GET.get('q') or request.GET.get('uid') or '').strip()
    status = (request.GET.get('status') or '').strip()
    category = (request.GET.get('category') or '').strip()
    vehicle_id = (request.GET.get('vehicle') or '').strip()
    db = _db()
    uid = _resolve_uid(db, query) if query else ''
    wallet, transactions = (None, [])
    reports, redemptions, catalog = [], [], []
    error = ''
    try:
        if tab == 'wallet' and uid:
            wallet, transactions = _load_wallet(db, uid)
        elif tab == 'reports':
            reports = _load_reports(db, uid, status, category, vehicle_id)
        elif tab == 'redemptions':
            redemptions = _load_redemptions(db, status)
            catalog = _load_catalog(db)
        elif tab == 'catalog':
            catalog = _load_catalog(db)
    except Exception as exc:
        error = str(exc)
    return {
        'tab': tab,
        'query': query,
        'uid': uid,
        'status': status,
        'category': category,
        'vehicle': vehicle_id,
        'wallet': wallet,
        'transactions': transactions,
        'reports': reports,
        'redemptions': redemptions,
        'catalog': catalog,
        'load_error': error,
        'form_key': uuid.uuid4().hex,
    }


def _back(tab, query=''):
    url = reverse('manage_rewards') + f'?tab={tab}'
    if query:
        url += f'&q={query}'
    return redirect(url)


def _adjust(uid, points, reason, key, actor):
    if not uid:
        raise ValueError('Choose a user first.')
    if points == 0 or abs(points) > 10000:
        raise ValueError('Adjustment must be between -10000 and 10000, and not zero.')
    if len(reason.strip()) < 4:
        raise ValueError('A reason of at least 4 characters is required.')
    if len(key.strip()) < 8:
        raise ValueError('Adjustment key is missing.')
    db = _db()
    user_ref = db.collection('users').document(uid)
    ledger_id = f'adjust_{key.strip()}'
    ledger_ref = user_ref.collection('reward_transactions').document(ledger_id)
    audit_ref = db.collection('wallet_audit_logs').document(ledger_id)
    transaction = db.transaction()

    @firestore.transactional
    def run(tx):
        user_snap = user_ref.get(transaction=tx)
        ledger_snap = ledger_ref.get(transaction=tx)
        if ledger_snap.exists:
            return False
        if not user_snap.exists:
            raise ValueError('User was not found.')
        balance = _int((user_snap.to_dict() or {}).get('rewardBalance'))
        if balance + points < 0:
            raise ValueError('That adjustment would make the wallet negative.')
        patch = {
            'rewardBalance': firestore.Increment(points),
            'walletUpdatedAt': firestore.SERVER_TIMESTAMP,
        }
        if points > 0:
            patch['lifetimeRewardPoints'] = firestore.Increment(points)
        tx.set(ledger_ref, {
            'transactionId': ledger_id,
            'uid': uid,
            'type': 'adjustment',
            'points': points,
            'status': 'completed',
            'reasonCode': 'admin_adjustment',
            'reason': reason.strip(),
            'reportId': '',
            'redemptionId': '',
            'relatedTransactionId': '',
            'idempotencyKey': key.strip(),
            'createdAt': firestore.SERVER_TIMESTAMP,
            'actorType': 'admin',
            'actorId': actor,
        })
        tx.set(user_ref, patch, merge=True)
        tx.set(audit_ref, {
            'action': 'adjustment',
            'uid': uid,
            'points': points,
            'reason': reason.strip(),
            'actorId': actor,
            'createdAt': firestore.SERVER_TIMESTAMP,
        })
        return True

    return run(transaction)


def _reverse(uid, transaction_id, reason, actor):
    if len(reason.strip()) < 4:
        raise ValueError('A reason of at least 4 characters is required.')
    db = _db()
    user_ref = db.collection('users').document(uid)
    original_ref = user_ref.collection('reward_transactions').document(transaction_id)
    reversal_id = f'reversal_{transaction_id}'
    reversal_ref = user_ref.collection('reward_transactions').document(reversal_id)
    audit_ref = db.collection('wallet_audit_logs').document(reversal_id)
    transaction = db.transaction()

    @firestore.transactional
    def run(tx):
        original = original_ref.get(transaction=tx)
        reversal = reversal_ref.get(transaction=tx)
        user_snap = user_ref.get(transaction=tx)
        if reversal.exists:
            return False
        data = original.to_dict() if original.exists else None
        if not data or data.get('type') != 'credit':
            raise ValueError('Only a credit can be reversed.')
        amount = _int(data.get('points'))
        if amount <= 0:
            raise ValueError('This credit has no points to reverse.')
        balance = _int((user_snap.to_dict() or {}).get('rewardBalance'))
        if balance - amount < 0:
            raise ValueError('Not enough available points to reverse this credit.')
        tx.set(reversal_ref, {
            'transactionId': reversal_id,
            'uid': uid,
            'type': 'reversal',
            'points': -amount,
            'status': 'completed',
            'reasonCode': 'admin_reversal',
            'reason': reason.strip(),
            'reportId': data.get('reportId') or '',
            'redemptionId': '',
            'relatedTransactionId': transaction_id,
            'idempotencyKey': reversal_id,
            'createdAt': firestore.SERVER_TIMESTAMP,
            'actorType': 'admin',
            'actorId': actor,
        })
        tx.set(user_ref, {
            'rewardBalance': firestore.Increment(-amount),
            'lifetimeRewardPoints': firestore.Increment(-amount),
            'walletUpdatedAt': firestore.SERVER_TIMESTAMP,
        }, merge=True)
        tx.set(audit_ref, {
            'action': 'reversal',
            'uid': uid,
            'points': -amount,
            'reason': reason.strip(),
            'relatedTransactionId': transaction_id,
            'actorId': actor,
            'createdAt': firestore.SERVER_TIMESTAMP,
        })
        return True

    return run(transaction)


def _fulfil(redemption_id, action, reason, reference, actor):
    db = _db()
    redemption_ref = db.collection('reward_redemptions').document(redemption_id)
    transaction = db.transaction()

    @firestore.transactional
    def run(tx):
        snap = redemption_ref.get(transaction=tx)
        if not snap.exists:
            raise ValueError('Redemption was not found.')
        redemption = snap.to_dict() or {}
        status = redemption.get('status')
        open_status = status in ('requested', 'processing')
        refund = False
        next_status = ''
        manual = False
        if action == 'processing' and status == 'requested':
            next_status = 'processing'
        elif action == 'fulfilled' and open_status:
            next_status = 'fulfilled'
        elif action == 'manually_redeemed' and open_status:
            next_status = 'fulfilled'
            manual = True
        elif action == 'rejected' and open_status:
            if len(reason.strip()) < 4:
                raise ValueError('A reason is required to reject a redemption.')
            next_status = 'rejected'
            refund = True
        else:
            raise ValueError('This redemption cannot move to that status.')
        reward_ref = db.collection('reward_catalog').document(redemption.get('rewardId') or '_')
        user_ref = db.collection('users').document(redemption.get('uid') or '_')
        refund_id = f'refund_{redemption_id}'
        ledger_ref = user_ref.collection('reward_transactions').document(refund_id)
        reward_snap = reward_ref.get(transaction=tx) if refund else None
        ledger_snap = ledger_ref.get(transaction=tx) if refund else None
        if refund and ledger_snap is not None and not ledger_snap.exists:
            cost = _int(redemption.get('pointsCost'))
            tx.set(ledger_ref, {
                'transactionId': refund_id,
                'uid': redemption.get('uid') or '',
                'type': 'refund',
                'points': cost,
                'status': 'completed',
                'reasonCode': 'redemption_rejected',
                'reason': reason.strip(),
                'reportId': '',
                'redemptionId': redemption_id,
                'relatedTransactionId': '',
                'idempotencyKey': refund_id,
                'createdAt': firestore.SERVER_TIMESTAMP,
                'actorType': 'admin',
                'actorId': actor,
            })
            tx.set(user_ref, {
                'rewardBalance': firestore.Increment(cost),
                'redeemedRewardPoints': firestore.Increment(-cost),
                'walletUpdatedAt': firestore.SERVER_TIMESTAMP,
            }, merge=True)
            if reward_snap is not None and reward_snap.exists and isinstance((reward_snap.to_dict() or {}).get('stock'), (int, float)):
                tx.set(reward_ref, {'stock': firestore.Increment(1)}, merge=True)
        update = {
            'status': next_status,
            'rejectionReason': reason.strip() if refund else (redemption.get('rejectionReason') or ''),
            'fulfilmentReference': reference.strip() or (redemption.get('fulfilmentReference') or ''),
            'processedAt': firestore.SERVER_TIMESTAMP,
        }
        if manual:
            update['manualRedeemed'] = True
            update['actorType'] = 'admin'
            update['actorId'] = actor
        tx.update(redemption_ref, update)
        tx.set(db.collection('wallet_audit_logs').document(f'fulfil_{redemption_id}_{next_status}'), {
            'action': 'fulfilment',
            'uid': redemption.get('uid') or '',
            'redemptionId': redemption_id,
            'status': next_status,
            'reason': reason.strip(),
            'actorId': actor,
            'createdAt': firestore.SERVER_TIMESTAMP,
        })
        return next_status

    return run(transaction)


def _save_catalog(data):
    title = (data.get('title') or '').strip()
    reward_id = (data.get('reward_id') or '').strip()
    cost = _int(data.get('points_cost'), default=-1)
    if len(title) < 2:
        raise ValueError('A reward title is required.')
    if cost <= 0:
        raise ValueError('Points cost must be greater than zero.')
    stock_raw = (data.get('stock') or '').strip()
    payload = {
        'title': title,
        'description': (data.get('description') or '').strip(),
        'pointsCost': cost,
        'active': data.get('active') == 'on',
        'terms': (data.get('terms') or '').strip(),
        'rewardType': (data.get('reward_type') or 'other').strip() or 'other',
        'updatedAt': firestore.SERVER_TIMESTAMP,
    }
    if stock_raw == '':
        payload['stock'] = firestore.DELETE_FIELD
    else:
        stock = _int(stock_raw, default=-1)
        if stock < 0:
            raise ValueError('Stock must be a number, or left empty for no limit.')
        payload['stock'] = stock
    db = _db()
    if reward_id:
        db.collection('reward_catalog').document(reward_id).set(payload, merge=True)
        return reward_id
    payload['createdAt'] = firestore.SERVER_TIMESTAMP
    ref = db.collection('reward_catalog').document()
    ref.set(payload)
    return ref.id


def _manual_redeem(uid, reward_id, reference, actor):
    """Redeem a catalog reward for a customer from the admin panel."""
    if not uid:
        raise ValueError('Enter the customer user ID or email.')
    if not reward_id:
        raise ValueError('Choose a reward.')
    db = _db()
    user_ref = db.collection('users').document(uid)
    reward_ref = db.collection('reward_catalog').document(reward_id)
    redemption_ref = db.collection('reward_redemptions').document()
    ledger_id = f'manual_{redemption_ref.id}'
    ledger_ref = user_ref.collection('reward_transactions').document(ledger_id)
    transaction = db.transaction()

    @firestore.transactional
    def run(tx):
        user_snap = user_ref.get(transaction=tx)
        reward_snap = reward_ref.get(transaction=tx)
        if not user_snap.exists:
            raise ValueError('User was not found.')
        if not reward_snap.exists:
            raise ValueError('Reward was not found.')
        user = user_snap.to_dict() or {}
        reward = reward_snap.to_dict() or {}
        if reward.get('active') is not True:
            raise ValueError('That reward is not active.')
        cost = _int(reward.get('pointsCost'))
        if cost <= 0:
            raise ValueError('Reward points cost is not set.')
        if _int(user.get('rewardBalance')) < cost:
            raise ValueError('This user does not have enough points.')
        stock = reward.get('stock')
        if isinstance(stock, (int, float)) and int(stock) <= 0:
            raise ValueError('That reward is out of stock.')
        tx.set(redemption_ref, {
            'uid': uid,
            'rewardId': reward_id,
            'pointsCost': cost,
            'status': 'fulfilled',
            'manualRedeemed': True,
            'rejectionReason': '',
            'fulfilmentReference': reference.strip(),
            'createdAt': firestore.SERVER_TIMESTAMP,
            'processedAt': firestore.SERVER_TIMESTAMP,
            'actorType': 'admin',
            'actorId': actor,
        })
        tx.set(ledger_ref, {
            'transactionId': ledger_id,
            'uid': uid,
            'type': 'redemption',
            'points': -cost,
            'status': 'completed',
            'reasonCode': 'manual_redemption',
            'reason': reference.strip() or 'Manually redeemed by admin',
            'reportId': '',
            'redemptionId': redemption_ref.id,
            'relatedTransactionId': '',
            'idempotencyKey': ledger_id,
            'createdAt': firestore.SERVER_TIMESTAMP,
            'actorType': 'admin',
            'actorId': actor,
        })
        tx.set(user_ref, {
            'rewardBalance': firestore.Increment(-cost),
            'redeemedRewardPoints': firestore.Increment(cost),
            'walletUpdatedAt': firestore.SERVER_TIMESTAMP,
        }, merge=True)
        if isinstance(stock, (int, float)):
            tx.set(reward_ref, {'stock': firestore.Increment(-1)}, merge=True)
        tx.set(db.collection('wallet_audit_logs').document(f'manual_{redemption_ref.id}'), {
            'action': 'manual_redemption',
            'uid': uid,
            'redemptionId': redemption_ref.id,
            'rewardId': reward_id,
            'points': cost,
            'actorId': actor,
            'createdAt': firestore.SERVER_TIMESTAMP,
        })
        return cost

    return run(transaction)


@require_http_methods(['GET', 'POST'])
def manage_rewards(request):
    gate = _require_admin(request)
    if gate:
        return gate
    if request.method == 'POST':
        action = (request.POST.get('action') or '').strip()
        query = (request.POST.get('q') or '').strip()
        tab = (request.POST.get('tab') or 'wallet').strip()
        try:
            if action == 'adjust':
                uid = _resolve_uid(_db(), request.POST.get('uid') or query)
                created = _adjust(
                    uid,
                    _int(request.POST.get('points'), default=0),
                    request.POST.get('reason') or '',
                    request.POST.get('idempotency_key') or '',
                    _actor(request),
                )
                messages.success(request, 'Adjustment already recorded.' if not created else 'Wallet adjustment recorded.')
                return _back('wallet', uid)
            if action == 'reverse':
                uid = (request.POST.get('uid') or '').strip()
                created = _reverse(uid, (request.POST.get('transaction_id') or '').strip(), request.POST.get('reason') or '', _actor(request))
                messages.success(request, 'Reversal already recorded.' if not created else 'Credit reversed.')
                return _back('wallet', uid)
            if action == 'fulfil':
                next_status = (request.POST.get('next_status') or '').strip()
                status = _fulfil(
                    (request.POST.get('redemption_id') or '').strip(),
                    next_status,
                    request.POST.get('reason') or '',
                    request.POST.get('reference') or '',
                    _actor(request),
                )
                label = 'manually redeemed' if next_status == 'manually_redeemed' else status
                messages.success(request, f'Redemption marked {label}.')
                return _back('redemptions')
            if action == 'manual_redeem':
                uid = _resolve_uid(_db(), request.POST.get('uid') or '')
                points = _manual_redeem(
                    uid,
                    (request.POST.get('reward_id') or '').strip(),
                    request.POST.get('reference') or '',
                    _actor(request),
                )
                messages.success(request, f'Manually redeemed {points} points for that customer.')
                return _back('redemptions')
            if action == 'catalog':
                reward_id = _save_catalog(request.POST)
                messages.success(request, f'Reward {reward_id} saved.')
                return _back('catalog')
            messages.error(request, 'Unknown wallet action.')
        except ValueError as exc:
            messages.error(request, str(exc))
        except Exception as exc:
            messages.error(request, f'Wallet update failed: {exc}')
        return _back(tab, query)

    if request.GET.get('export') == '1':
        loaded = _page(request)
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="issue_reports.csv"'
        writer = csv.writer(response)
        writer.writerow(['id', 'vehicle', 'reporter', 'category', 'status', 'verification', 'points', 'created'])
        for report in loaded['reports']:
            writer.writerow([
                report['id'], report['vehicle_id'], report['reporter_uid'], report['category'],
                report['status'], report['verification'], report['points'], report['created'],
            ])
        return response
    return render(request, 'manage_rewards.html', _page(request))
