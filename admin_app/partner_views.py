"""Admin pages for the SudoTag Partner Programme (see partner_service.py)."""
from __future__ import annotations

import csv

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from . import partner_service as svc

TABS = ('applications', 'partners', 'withdrawals', 'commissions', 'settings', 'partner')


EXPORTS = {
    'partners': (
        ['Partner ID', 'Name', 'Mobile', 'City', 'Status', 'Verified tags', 'Pending tags',
         'Available', 'Pending', 'On hold', 'Paid out', 'Lifetime', 'Target', 'Payout', 'Applied', 'Approved'],
        lambda status: svc.list_partners(status=status, limit=5000),
        lambda r: [r['partner_id'], r['name'], r['phone'], r['city'], r['status'], r['verified_tags'],
                   r['pending_tags'], r['available'], r['pending'], r['on_hold'], r['paid'], r['lifetime'],
                   r['target'], r['payout_display'], r['applied'], r['approved']],
    ),
    'commissions': (
        ['Created', 'Order ID', 'Partner ID', 'Source', 'Tags', 'Amount', 'Status', 'Available at', 'Reversed reason'],
        lambda status: svc.list_commissions(status=status, limit=10000),
        lambda r: [r['created'], r['order_id'], r['partner_id'], r['source'], r['quantity'], r['amount'],
                   r['status'], r['available_at'], r['reversed_reason']],
    ),
    'withdrawals': (
        ['Requested', 'Partner ID', 'Name', 'Amount', 'Status', 'Method', 'UPI', 'Account name',
         'Account number', 'IFSC', 'UTR', 'Reject reason', 'Decided'],
        lambda status: svc.list_withdrawals(status=status, limit=10000),
        lambda r: [r['requested'], r['partner_id'], r['partner_name'], r['amount'], r['status'], r['method'],
                   r['upi'], r['account_name'], r['account_number'], r['ifsc'], r['utr'], r['reject_reason'],
                   r['decided']],
    ),
}


def _export_csv(kind, status):
    header, load, row = EXPORTS[kind]
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="sudotag_partner_{kind}.csv"'
    response.write('\ufeff')  # Excel opens UTF-8 (₹, Indic names) correctly
    writer = csv.writer(response)
    writer.writerow(header)
    for r in load(status):
        writer.writerow([_safe_cell(v) for v in row(r)])
    return response


def _safe_cell(v):
    """Stop spreadsheet formula injection from user-typed text."""
    s = '' if v is None else str(v)
    return "'" + s if s[:1] in ('=', '+', '-', '@') and not s.lstrip('-').replace('.', '', 1).isdigit() else s


def _require_admin(request):
    if not request.session.get('admin'):
        messages.error(request, 'Admin access required')
        return redirect('admin_login')
    return None


def _actor(request):
    return request.session.get('user_id') or request.session.get('email') or 'django-admin'


def _back(tab, **params):
    url = reverse('manage_partners') + f'?tab={tab}'
    for k, v in params.items():
        if v:
            url += f'&{k}={v}'
    return redirect(url)


@require_http_methods(['GET', 'POST'])
def manage_partners(request):
    gate = _require_admin(request)
    if gate:
        return gate

    if request.method == 'POST':
        action = (request.POST.get('action') or '').strip()
        tab = (request.POST.get('tab') or 'applications').strip()
        uid = (request.POST.get('uid') or '').strip()
        try:
            if action in ('approve', 'reject', 'suspend', 'reactivate'):
                status = svc.decide_partner(uid, action, _actor(request), request.POST.get('reason') or '')
                messages.success(
                    request,
                    'Partner approved — their Partner ID is being issued.' if action == 'approve'
                    else f'Partner {status}.',
                )
            elif action in ('withdrawal_paid', 'withdrawal_rejected'):
                svc.decide_withdrawal(
                    (request.POST.get('withdrawal_id') or '').strip(),
                    'paid' if action == 'withdrawal_paid' else 'rejected',
                    _actor(request),
                    utr=request.POST.get('utr') or '',
                    reason=request.POST.get('reason') or '',
                )
                messages.success(
                    request,
                    'Withdrawal marked paid.' if action == 'withdrawal_paid'
                    else 'Withdrawal rejected — the amount returns to the partner\'s wallet.',
                )
            elif action == 'reverse_commission':
                svc.request_commission_reversal(
                    (request.POST.get('order_id') or '').strip(),
                    request.POST.get('reason') or '',
                    _actor(request),
                )
                messages.success(request, 'Reversal requested — the wallet updates in a few seconds.')
            elif action == 'save_settings':
                svc.save_config(svc.parse_config_form(request.POST), _actor(request))
                messages.success(request, 'Programme settings saved.')
            else:
                messages.error(request, 'Unknown action.')
        except svc.PartnerAdminError as exc:
            messages.error(request, str(exc))
        except Exception:
            messages.error(request, 'Could not save that change. Please try again.')
        return _back(tab, uid=uid if tab == 'partner' else '')

    export = (request.GET.get('export') or '').strip()
    if export in EXPORTS:
        return _export_csv(export, (request.GET.get('status') or '').strip())

    tab = (request.GET.get('tab') or 'applications').strip()
    if tab not in TABS:
        tab = 'applications'
    ctx = {
        'tab': tab,
        'q': (request.GET.get('q') or '').strip(),
        'status': (request.GET.get('status') or '').strip(),
        'load_error': '',
    }
    try:
        ctx['counts'] = svc.summary()
        if tab == 'applications':
            ctx['rows'] = svc.list_partners(status='pending', query=ctx['q'])
        elif tab == 'partners':
            status = ctx['status'] if ctx['status'] in ('approved', 'suspended', 'rejected') else 'approved'
            ctx['status'] = status
            ctx['rows'] = svc.list_partners(status=status, query=ctx['q'])
        elif tab == 'withdrawals':
            status = ctx['status'] if ctx['status'] in svc.WITHDRAWAL_STATUSES else 'requested'
            ctx['status'] = status
            ctx['rows'] = svc.list_withdrawals(status=status)
        elif tab == 'commissions':
            ctx['rows'] = svc.list_commissions(status=ctx['status'])
        elif tab == 'settings':
            ctx['config'] = svc.load_config()
        elif tab == 'partner':
            uid = (request.GET.get('uid') or '').strip()
            ctx['detail'] = svc.partner_detail(uid) if uid else None
            ctx['uid'] = uid
    except Exception as exc:
        ctx['load_error'] = str(exc)
        ctx.setdefault('counts', {})
    return render(request, 'manage_partners.html', ctx)
