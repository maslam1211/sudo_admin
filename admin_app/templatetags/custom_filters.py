from pathlib import Path

from django import template
from django.conf import settings
from django.template.defaultfilters import floatformat
from django.urls import reverse
import pytz
from datetime import datetime

register = template.Library()

_SUDO_MOBILE_FLOW_CSS = (
    Path(settings.BASE_DIR)
    / 'admin_app'
    / 'static'
    / 'assets'
    / 'css'
    / 'sudo_mobile_flow.css'
)
_LANDING_ROOT = Path(settings.BASE_DIR) / 'static' / 'landing'


def _landing_asset_mtime(relative_path):
    path = _LANDING_ROOT / relative_path
    return int(path.stat().st_mtime) if path.is_file() else 0


@register.simple_tag
def landing_asset(relative_path):
    """Landing images/CSS/JS via Django — works when /static/ is stale on production."""
    relative_path = relative_path.replace('\\', '/').lstrip('/')
    if relative_path.startswith('landing/'):
        relative_path = relative_path[len('landing/') :]
    version = _landing_asset_mtime(relative_path)
    url = reverse('landing_asset', kwargs={'asset_path': relative_path})
    return f'{url}?v={version}' if version else url


@register.simple_tag
def sudo_mobile_flow_css_url():
    """Cache-bust mobile flow CSS when the file changes (deploy / server restart)."""
    version = int(_SUDO_MOBILE_FLOW_CSS.stat().st_mtime) if _SUDO_MOBILE_FLOW_CSS.is_file() else 0
    return f'{reverse("sudo_mobile_flow_css")}?v={version}'

@register.filter
def percentage(value, arg):
    try:
        return floatformat((float(value) / float(arg)) * 100, 2)
    except (ValueError, ZeroDivisionError):
        return 0
    

@register.filter(name='get_item')
def get_item(dictionary, key):
    return dictionary.get(key, 'Unknown')


@register.filter(name='to_ist')
def to_ist(value):
    """Convert timestamp to Indian Standard Time (IST)"""
    if not value:
        return value
    
    ist = pytz.timezone('Asia/Kolkata')
    
    # Handle Firestore timestamp
    if hasattr(value, 'to_datetime'):
        try:
            dt = value.to_datetime()
            if dt.tzinfo:
                dt = dt.astimezone(ist)
            else:
                dt = ist.localize(dt)
            return dt
        except:
            return value
    
    # Handle datetime objects
    if isinstance(value, datetime):
        if value.tzinfo:
            return value.astimezone(ist)
        else:
            return ist.localize(value)
    
    # Handle string timestamps
    if isinstance(value, str):
        try:
            # Try parsing common formats
            formats = [
                "%B %d, %Y at %I:%M:%S %p UTC%z",
                "%B %d, %Y at %I:%M:%S %p",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%dT%H:%M:%S%z",
            ]
            for fmt in formats:
                try:
                    dt = datetime.strptime(value.replace('UTC+5:30', '+05:30'), fmt)
                    if dt.tzinfo:
                        dt = dt.astimezone(ist)
                    else:
                        dt = ist.localize(dt)
                    return dt
                except:
                    continue
        except:
            pass
    
    return value

@register.filter(name='to_ist_format')
def to_ist_format(value):
    """Convert timestamp to IST and format as 'Monday, November 24, 2025 - 12:30 AM'"""
    if not value:
        return value
    
    ist = pytz.timezone('Asia/Kolkata')
    dt = None
    
    # Handle Firestore timestamp
    if hasattr(value, 'to_datetime'):
        try:
            dt = value.to_datetime()
            if dt.tzinfo:
                dt = dt.astimezone(ist)
            else:
                dt = ist.localize(dt)
        except:
            return value
    
    # Handle datetime objects
    elif isinstance(value, datetime):
        if value.tzinfo:
            dt = value.astimezone(ist)
        else:
            dt = ist.localize(value)
    
    # Handle string timestamps
    elif isinstance(value, str):
        try:
            formats = [
                "%B %d, %Y at %I:%M:%S %p UTC%z",
                "%B %d, %Y at %I:%M:%S %p",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%dT%H:%M:%S%z",
            ]
            for fmt in formats:
                try:
                    dt = datetime.strptime(value.replace('UTC+5:30', '+05:30'), fmt)
                    if dt.tzinfo:
                        dt = dt.astimezone(ist)
                    else:
                        dt = ist.localize(dt)
                    break
                except:
                    continue
        except:
            pass
    
    if dt:
        return dt.strftime("%A, %B %d, %Y - %I:%M %p")
    
    return value