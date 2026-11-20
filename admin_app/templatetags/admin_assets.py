import os

from django import template
from django.urls import reverse

from admin_app.asset_views import asset_path

register = template.Library()


@register.simple_tag
def admin_asset(path):
    """URL for an admin theme file, versioned by its modified time so browsers refetch after a deploy."""
    found = asset_path(path)
    url = reverse('admin_asset', args=[path])
    return f"{url}?v={int(os.path.getmtime(found))}" if found else url
