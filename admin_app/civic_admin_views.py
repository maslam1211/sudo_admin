"""Admin screens for CivicSense: reports, awareness campaigns, Civic Points."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from django.contrib import messages
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from . import civic_admin as ca

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

STATUS_MESSAGES = {
    'under_review': 'Report marked under review.',
    'verified': 'Report verified. The reporter earns Civic Points unless they are flagged.',
    'resolved': 'Report marked resolved.',
    'rejected': 'Report closed as not accepted. Any points it earned were taken back.',
    'duplicate': 'Report closed as a duplicate. Any points it earned were taken back.',
}


def _db():
    from .views import db
    return db


def _gate(request):
    if not request.session.get('admin'):
        return redirect('admin_login')
    return None


def _email(request) -> str:
    return request.session.get('email') or ''


def _safe_next(request, fallback: str) -> str:
    nxt = request.POST.get('next') or ''
    return nxt if nxt.startswith('/') and not nxt.startswith('//') else fallback


# ─── Reports ────────────────────────────────────────────────────────────────

@require_GET
def civic_reports(request):
    gate = _gate(request)
    if gate:
        return gate
    state = request.GET.get('state') or 'open'
    if state not in ca.FILTERS:
        state = 'open'
    query = (request.GET.get('q') or '').strip()[:100]
    category = request.GET.get('category') or ''
    if category not in ca.CATEGORY_LABELS:
        category = ''
    db = _db()
    error = ''
    try:
        result = ca.list_reports(db, state=state, query=query, category=category)
    except Exception as exc:
        logger.exception('civic reports list failed: %s', exc)
        result = {'reports': [], 'counts': {k: 0 for k in ca.FILTERS}}
        error = 'Could not load CivicSense reports from Firebase. Try again in a moment.'
    try:
        stats = ca.get_stats(db)
    except Exception:
        stats = {}
    filters = [
        ('open', 'Needs review', 'fa-inbox'),
        ('disputed', 'Disputed', 'fa-balance-scale'),
        ('flagged', 'Flagged reporters', 'fa-user-shield'),
        ('verified', 'Verified', 'fa-check'),
        ('resolved', 'Resolved', 'fa-check-double'),
        ('closed', 'Closed', 'fa-archive'),
        ('all', 'All', 'fa-layer-group'),
    ]
    filters = [(key, label, icon, result['counts'].get(key, 0)) for key, label, icon in filters]
    return render(request, 'civic_reports.html', {
        'reports': result['reports'],
        'counts': result['counts'],
        'state': state,
        'query': query,
        'category': category,
        'categories': ca.CATEGORY_LABELS,
        'filters': filters,
        'stats': stats,
        'error': error,
    })


@require_GET
def civic_report_detail(request, doc_id):
    gate = _gate(request)
    if gate:
        return gate
    detail = ca.get_report_detail(_db(), doc_id)
    if not detail:
        raise Http404('Report not found')
    detail['back_state'] = request.GET.get('from') or 'open'
    return render(request, 'civic_report_detail.html', detail)


@require_POST
def civic_report_status(request, doc_id):
    gate = _gate(request)
    if gate:
        return gate
    status = request.POST.get('status') or ''
    back = _safe_next(request, reverse('civic_report_detail', args=[doc_id]))
    try:
        ca.update_report_status(_db(), doc_id, status, request.POST.get('note') or '', _email(request),
                                dup_of=request.POST.get('dup_of') or '')
    except ca.CivicAdminError as exc:
        messages.error(request, str(exc))
    except Exception as exc:
        logger.exception('civic report status failed: %s', exc)
        messages.error(request, 'Could not update the report. Try again.')
    else:
        messages.success(request, STATUS_MESSAGES.get(status, 'Report updated.'))
    return redirect(back)


@require_POST
def civic_report_flag(request, doc_id):
    gate = _gate(request)
    if gate:
        return gate
    action = request.POST.get('action') or ''
    db = _db()
    try:
        if action == 'flag':
            ca.set_abuse_flag(db, doc_id, True, _email(request), request.POST.get('note') or '')
            messages.success(request, 'Reporter flagged. This report will not earn Civic Points.')
        elif action == 'unflag':
            ca.set_abuse_flag(db, doc_id, False, _email(request), request.POST.get('note') or '')
            messages.success(request, 'Flag cleared. Points follow your next decision on this report.')
        elif action == 'dispute_keep':
            ca.resolve_dispute(db, doc_id, _email(request), request.POST.get('note') or '')
            messages.success(request, 'Dispute reviewed. The report stays as it is.')
        elif action == 'delete_evidence':
            n = ca.delete_evidence_now(db, doc_id, _email(request))
            messages.success(request, f'Deleted {n} photo{"s" if n != 1 else ""} from storage.')
        else:
            messages.error(request, 'Unknown action.')
    except ca.CivicAdminError as exc:
        messages.error(request, str(exc))
    except Exception as exc:
        logger.exception('civic report flag action failed: %s', exc)
        messages.error(request, 'Could not update the report. Try again.')
    return redirect(reverse('civic_report_detail', args=[doc_id]))


@require_GET
def civic_report_evidence(request, doc_id, index):
    """Streams an evidence photo. Evidence is private, so it is never linked
    directly; the admin session is the only way in."""
    gate = _gate(request)
    if gate:
        return HttpResponse(status=403)
    snap = _db().collection(ca.REPORTS).document(doc_id).get()
    if not snap.exists:
        raise Http404()
    report = ca.normalize_report(doc_id, snap.to_dict() or {})
    try:
        data, content_type = ca.read_evidence(report, int(index))
    except ca.CivicAdminError:
        raise Http404()
    except Exception as exc:
        logger.warning('civic evidence read failed: %s', exc)
        raise Http404()
    if content_type not in ('image/jpeg', 'image/png', 'image/webp'):
        content_type = 'image/jpeg'
    response = HttpResponse(data, content_type=content_type)
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@require_POST
def civic_stats_recount(request):
    gate = _gate(request)
    if gate:
        return gate
    try:
        values = ca.recount_stats(_db())
    except Exception as exc:
        logger.exception('civic stats recount failed: %s', exc)
        messages.error(request, 'Could not recount the impact numbers. Try again.')
    else:
        messages.success(request, 'Impact numbers recounted: {totalReports} reports, {resolvedReports} resolved, '
                                  '{activeReporters} reporters, {activeCampaigns} live campaigns.'.format(**values))
    return redirect(_safe_next(request, reverse('civic_reports')))


# ─── Awareness campaigns ────────────────────────────────────────────────────

@require_GET
def civic_awareness(request):
    gate = _gate(request)
    if gate:
        return gate
    try:
        campaigns = ca.list_campaigns(_db())
        error = ''
    except Exception as exc:
        logger.exception('civic awareness list failed: %s', exc)
        campaigns, error = [], 'Could not load campaigns from Firebase.'
    return render(request, 'civic_awareness.html', {
        'campaigns': campaigns,
        'error': error,
        'live_count': sum(1 for c in campaigns if c['state'] == 'live'),
        'scheduled_count': sum(1 for c in campaigns if c['state'] == 'scheduled'),
        'hidden_count': sum(1 for c in campaigns if c['state'] == 'hidden'),
    })


@require_http_methods(['GET', 'POST'])
def civic_awareness_edit(request, campaign_id=None):
    gate = _gate(request)
    if gate:
        return gate
    db = _db()
    campaign = None
    if campaign_id:
        campaign = ca.get_campaign(db, campaign_id)
        if not campaign:
            raise Http404('Campaign not found')

    form = {}
    if request.method == 'POST':
        form = {
            'title': request.POST.get('title', ''),
            'description': request.POST.get('description', ''),
            'category': request.POST.get('category', 'general'),
            'link_url': request.POST.get('link_url', ''),
            'cover_url': request.POST.get('cover_url', ''),
            'publish_at': request.POST.get('publish_at', ''),
            'is_active': request.POST.get('is_active') == 'on',
            'remove_cover': request.POST.get('remove_cover') == 'on',
        }
        try:
            ca.save_campaign(db, campaign_id, form, _email(request), upload=request.FILES.get('cover'))
        except ca.CivicAdminError as exc:
            messages.error(request, str(exc))
        except Exception as exc:
            logger.exception('civic awareness save failed: %s', exc)
            messages.error(request, 'Could not save the campaign. Try again.')
        else:
            messages.success(request, 'Campaign saved.' if campaign_id else 'Campaign created.')
            return redirect('civic_awareness')
    elif campaign:
        form = {
            'title': campaign['title'],
            'description': campaign['description'],
            'category': campaign['category'],
            'link_url': campaign['link_url'],
            'cover_url': campaign['cover_url'],
            'publish_at': campaign['publish_at'].astimezone(IST).strftime('%Y-%m-%dT%H:%M')
            if campaign['publish_at'] else '',
            'is_active': campaign['is_active'],
        }
    else:
        form = {'category': 'parking_tips', 'is_active': True,
                'publish_at': datetime.now(IST).strftime('%Y-%m-%dT%H:%M')}

    return render(request, 'civic_awareness_edit.html', {
        'campaign': campaign,
        'form': form,
        'categories': ca.AWARENESS_CATEGORIES,
    })


@require_POST
def civic_awareness_action(request, campaign_id):
    gate = _gate(request)
    if gate:
        return gate
    action = request.POST.get('action') or ''
    db = _db()
    try:
        if action in ('show', 'hide'):
            ca.set_campaign_active(db, campaign_id, action == 'show', _email(request))
            messages.success(request, 'Campaign is visible in the app.' if action == 'show'
                             else 'Campaign hidden from the app.')
        elif action == 'delete':
            ca.delete_campaign(db, campaign_id)
            messages.success(request, 'Campaign deleted.')
        else:
            messages.error(request, 'Unknown action.')
    except ca.CivicAdminError as exc:
        messages.error(request, str(exc))
    except Exception as exc:
        logger.exception('civic awareness action failed: %s', exc)
        messages.error(request, 'Could not update the campaign. Try again.')
    return redirect('civic_awareness')


# ─── Civic Points ───────────────────────────────────────────────────────────

def _month_options(now: datetime, count: int = 6):
    out = []
    year, month = now.year, now.month
    for _ in range(count):
        key = f'{year:04d}-{month:02d}'
        out.append((key, datetime(year, month, 1).strftime('%B %Y')))
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return out


@require_GET
def civic_points(request):
    gate = _gate(request)
    if gate:
        return gate
    now = datetime.now(timezone.utc)
    months = _month_options(now)
    month = request.GET.get('month') or months[0][0]
    if month not in dict(months):
        month = months[0][0]
    query = (request.GET.get('q') or '').strip()[:100]
    db = _db()
    error = ''
    try:
        members = ca.list_members(db, query=query)
        leaderboard = ca.get_leaderboard(db, month)
    except Exception as exc:
        logger.exception('civic points list failed: %s', exc)
        members, leaderboard, error = [], [], 'Could not load Civic Points from Firebase.'
    return render(request, 'civic_points.html', {
        'members': members,
        'leaderboard': leaderboard,
        'months': months,
        'month': month,
        'query': query,
        'error': error,
        'points_rules': ca.POINTS,
        'levels': ca.LEVELS,
        'total_points': sum(m['total'] for m in members),
        'public_count': sum(1 for m in members if m['show']),
    })


@require_GET
def civic_member(request, uid):
    gate = _gate(request)
    if gate:
        return gate
    member = ca.get_member(_db(), uid)
    if member is None:
        raise Http404()
    return render(request, 'civic_member.html', {'member': member, 'max_adjust': ca.MAX_ADJUST_POINTS})


@require_POST
def civic_member_action(request, uid):
    gate = _gate(request)
    if gate:
        return gate
    action = request.POST.get('action') or ''
    db = _db()
    try:
        if action == 'adjust':
            applied = ca.adjust_points(db, uid, request.POST.get('points'), request.POST.get('reason') or '',
                                       _email(request))
            messages.success(request, f'{applied:+d} Civic Points applied.')
        elif action == 'hide_name':
            ca.hide_public_name(db, uid, _email(request))
            messages.success(request, 'Name removed from the leaderboard. They show as "SudoTag member".')
        else:
            messages.error(request, 'Unknown action.')
    except ca.CivicAdminError as exc:
        messages.error(request, str(exc))
    except Exception as exc:
        logger.exception('civic member action failed: %s', exc)
        messages.error(request, 'Could not update Civic Points. Try again.')
    return redirect(reverse('civic_member', args=[uid]))
