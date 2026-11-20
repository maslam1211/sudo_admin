"""Admin screens for Civic Sense (community post) reports."""

from __future__ import annotations

import logging

from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST

from . import civic_sense

logger = logging.getLogger(__name__)

ACTION_MESSAGES = {
    'approve': 'Post approved and kept live. Its reports are marked as kept.',
    'remove': 'Post removed from Civic Sense. Its reports are marked as removed.',
    'dismiss': 'Reports dismissed. The post stays live and its report count is reset.',
}


def _get_db():
    from .views import db
    return db


def _require_admin(request):
    if not request.session.get('admin'):
        return redirect('admin_login')
    return None


@require_http_methods(['GET'])
def civic_sense_reports(request):
    gate = _require_admin(request)
    if gate:
        return gate
    state = request.GET.get('state') or 'reported'
    if state not in civic_sense.FILTERS:
        state = 'reported'
    query = (request.GET.get('q') or '').strip()[:100]
    try:
        result = civic_sense.list_posts(_get_db(), state=state, query=query)
        error = ''
    except Exception as exc:
        logger.exception('civic sense list failed: %s', exc)
        result = {'posts': [], 'counts': {k: 0 for k in civic_sense.FILTERS}}
        error = 'Could not load Civic Sense posts from Firebase. Try again in a moment.'
    filters = [
        ('reported', 'Reported', 'fa-flag'),
        ('pending', 'Pending review', 'fa-hourglass-half'),
        ('live', 'Live', 'fa-check'),
        ('removed', 'Removed', 'fa-ban'),
        ('all', 'All posts', 'fa-layer-group'),
    ]
    return render(request, 'civic_sense_reports.html', {
        'posts': result['posts'],
        'counts': result['counts'],
        'state': state,
        'query': query,
        'filters': filters,
        'error': error,
    })


@require_http_methods(['GET'])
def civic_sense_post(request, post_id):
    gate = _require_admin(request)
    if gate:
        return gate
    db = _get_db()
    snap = db.collection(civic_sense.POSTS).document(post_id).get()
    if not snap.exists:
        raise Http404('Post not found')
    post = civic_sense.normalize_post(snap.id, snap.to_dict() or {})
    reports = civic_sense.get_reports(db, post_id)
    comments = civic_sense.get_comments(db, post_id)
    users = civic_sense.get_users(db, [post['author_id']] + [r['reporter_id'] for r in reports])
    for report in reports:
        report['user'] = users.get(report['reporter_id'], {})
    return render(request, 'civic_sense_post.html', {
        'post': post,
        'author': users.get(post['author_id'], {}),
        'reports': reports,
        'comments': comments,
        'back_state': request.GET.get('from') or 'reported',
    })


@require_POST
def civic_sense_moderate(request, post_id):
    gate = _require_admin(request)
    if gate:
        return gate
    action = request.POST.get('action') or ''
    note = request.POST.get('note') or ''
    back = request.POST.get('next') or ''
    if action == 'remove' and not note.strip():
        messages.error(request, 'Add a short reason before removing a post.')
        return redirect(reverse('civic_sense_post', args=[post_id]))
    try:
        civic_sense.moderate(_get_db(), post_id, action, request.session.get('email') or '', note)
    except ValueError as exc:
        messages.error(request, str(exc))
    except Exception as exc:
        logger.exception('civic sense moderate failed: %s', exc)
        messages.error(request, 'Could not update the post. Try again.')
    else:
        messages.success(request, ACTION_MESSAGES[action])
    if back.startswith('/') and not back.startswith('//'):
        return redirect(back)
    return redirect(reverse('civic_sense_post', args=[post_id]))
