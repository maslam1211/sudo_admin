from django import template
from django.template.defaultfilters import floatformat
import pytz
from datetime import datetime

register = template.Library()

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