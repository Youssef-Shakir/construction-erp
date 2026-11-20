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


@register.simple_tag
def scan_inbox_items(limit=50):
    """Unassigned scan-inbox files, for the 'attach from inbox' picker."""
    from apps.core.attachments import inbox_items
    return list(inbox_items()[:limit])


@register.simple_tag
def attachment_accept():
    """Value for <input type=file accept=...>."""
    from apps.core.attachments import ACCEPT_ATTR
    return ACCEPT_ATTR


@register.filter(name='filesize')
def filesize(value):
    """Human readable file size."""
    try:
        size = float(value or 0)
    except (TypeError, ValueError):
        return ''
    for unit in ('B', 'KB', 'MB', 'GB'):
        if size < 1024 or unit == 'GB':
            return f'{size:.0f} {unit}' if unit == 'B' else f'{size:.1f} {unit}'
        size /= 1024


@register.simple_tag(takes_context=True)
def can_manage_inbox(context):
    from apps.accounts.permissions import can_manage_scan_inbox
    request = context.get('request')
    return bool(request) and can_manage_scan_inbox(request.user)


@register.simple_tag(takes_context=True)
def can_delete_attachment(context, attachment):
    from apps.accounts.permissions import can_delete_attachment as check
    request = context.get('request')
    return bool(request) and check(request.user, attachment)
