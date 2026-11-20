"""Serve the admin theme's CSS/JS through Django at /admin/assets/<path>.

On the VPS, nginx serves /static/ from its own folder, which collectstatic does
not update, so newly added theme files 404 there and admin pages show
unstyled. /admin/ is always proxied to Django, so serving these few files
here makes every deploy work with just git pull + restart.
"""

from __future__ import annotations

import mimetypes
import os

from django.contrib.staticfiles import finders
from django.http import FileResponse, Http404
from django.views.decorators.http import require_GET

# Only the admin theme files; everything else keeps using /static/.
ALLOWED = {
    'assets/css/sudotag-admin.css',
    'assets/css/sudotag-auth.css',
    'assets/js/sudotag-ui.js',
    'assets/js/sudotag-charts.js',
}


def asset_path(path: str):
    if path not in ALLOWED:
        return None
    found = finders.find(path)
    return found if found and os.path.isfile(found) else None


@require_GET
def admin_asset(request, path):
    found = asset_path(path)
    if not found:
        raise Http404('Unknown asset')
    content_type = mimetypes.guess_type(found)[0] or 'application/octet-stream'
    if content_type.startswith('text/') or content_type.endswith('javascript'):
        content_type += '; charset=utf-8'
    response = FileResponse(open(found, 'rb'), content_type=content_type)
    # URLs carry ?v=<file mtime>, so a changed file gets a new URL: cache hard.
    response['Cache-Control'] = 'public, max-age=31536000, immutable' if request.GET.get('v') else 'no-cache'
    return response
