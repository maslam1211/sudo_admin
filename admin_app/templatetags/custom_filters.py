from django import template
from django.template.defaultfilters import floatformat

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