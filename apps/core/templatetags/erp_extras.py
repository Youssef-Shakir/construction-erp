"""
Shared template helpers for Construction ERP.
"""
from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


@register.filter(name='thousands')
def thousands(value):
    """
    Format a number with thousand separators (1,234,567.89).

    Always uses ',' for grouping and '.' for the decimal point regardless
    of the active locale - money in this app is displayed in fixed Western
    notation (see the ".money" CSS class, which is forced left-to-right).
    Non-numeric or empty values pass through unchanged.
    """
    if value is None or value == '':
        return value
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return value

    sign, digits, exponent = amount.as_tuple()
    decimals = -exponent if exponent < 0 else 0
    return format(amount, f',.{decimals}f') if decimals else format(amount, ',.0f')
