"""JSON endpoints for saving, editing and deleting custom QR sticker designs."""

from __future__ import annotations

import logging

from django.http import JsonResponse
from django.views.decorators.http import require_POST

from . import qr_designs

logger = logging.getLogger(__name__)


def _get_db():
    from .views import db
    return db


def _denied():
    return JsonResponse({'success': False, 'error': 'Admin access required.'}, status=403)


def _box(request):
    return (request.POST.get('box_x'), request.POST.get('box_y'), request.POST.get('box_size'))


def _run(fn):
    try:
        return JsonResponse({'success': True, 'design': fn()})
    except qr_designs.DesignError as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=400)
    except Exception as exc:
        if type(exc).__module__.startswith('cloudinary'):
            logger.exception('qr design upload to Cloudinary failed: %s', exc)
            return JsonResponse({'success': False, 'error': "The image couldn't be uploaded to storage. Try again in a minute."},
                                status=502)
        logger.exception('qr design request failed: %s', exc)
        return JsonResponse({'success': False, 'error': 'Something went wrong. Try again.'}, status=500)


@require_POST
def qr_design_save(request):
    if not request.session.get('admin'):
        return _denied()
    upload = request.FILES.get('design_image')
    if not upload:
        return JsonResponse({'success': False, 'error': 'Choose a design image.'}, status=400)
    return _run(lambda: qr_designs.save_design(
        _get_db(),
        upload=upload,
        name=request.POST.get('name') or '',
        purpose=request.POST.get('purpose') or 'user',
        box_raw=_box(request),
        width_mm_raw=request.POST.get('width_mm'),
        white_backing=request.POST.get('white_backing') == 'on',
        admin_email=request.session.get('email') or '',
    ))


@require_POST
def qr_design_update(request, design_id):
    if not request.session.get('admin'):
        return _denied()
    return _run(lambda: qr_designs.update_design(
        _get_db(),
        design_id,
        box_raw=_box(request),
        width_mm_raw=request.POST.get('width_mm'),
        white_backing=request.POST.get('white_backing') == 'on',
        name=request.POST.get('name') or '',
    ))


@require_POST
def qr_design_delete(request, design_id):
    if not request.session.get('admin'):
        return _denied()

    def go():
        qr_designs.delete_design(_get_db(), design_id)
        return {'id': design_id}
    return _run(go)
