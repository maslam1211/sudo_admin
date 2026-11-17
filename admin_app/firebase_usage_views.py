"""Admin page: Firebase usage, estimated cost and (optional) exact bill."""
from __future__ import annotations

import logging

from django.contrib import messages
from django.shortcuts import redirect, render

from . import firebase_usage as fu

logger = logging.getLogger(__name__)


def firebase_usage(request):
    if not request.session.get('admin'):
        messages.error(request, 'Admin access required')
        return redirect('admin_login')

    refresh = request.GET.get('refresh') == '1'
    ctx = {'usage': None, 'usage_error': None, 'billing': None, 'billing_error': None,
           'billing_configured': bool(fu.billing_table())}
    try:
        ctx['usage'] = fu.get_usage_summary(refresh=refresh)
    except fu.UsageUnavailable as exc:
        ctx['usage_error'] = str(exc)
    except Exception:
        logger.exception('Loading Firebase usage failed')
        ctx['usage_error'] = 'Could not load Firebase usage. Try again in a minute.'

    project = (ctx['usage'] or {}).get('project') or ''
    if ctx['billing_configured'] and project:
        try:
            ctx['billing'] = fu.get_billing(project, refresh=refresh)
        except fu.UsageUnavailable as exc:
            ctx['billing_error'] = str(exc)
        except Exception:
            logger.exception('Loading billing export failed')
            ctx['billing_error'] = 'Could not load the billing export. Try again in a minute.'

    if refresh:
        return redirect('firebase_usage')
    return render(request, 'firebase_usage.html', ctx)
