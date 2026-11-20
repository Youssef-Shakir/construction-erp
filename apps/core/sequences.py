"""
Gap-tolerant, concurrency-safe document numbering (INV-000001, BILL-000001...).

The previous scheme (`last.id + 1`) let two simultaneous saves pick the same
number and crash on the unique constraint. Here each prefix has a counter row
that is locked (SELECT ... FOR UPDATE) while the next value is taken.
"""
from django.db import IntegrityError, transaction


def _max_existing(model, field, prefix):
    """Highest numeric suffix already used for `prefix` (seeds a new counter)."""
    highest = 0
    values = model.objects.filter(**{f'{field}__startswith': f'{prefix}-'}).values_list(field, flat=True)
    for value in values:
        suffix = value[len(prefix) + 1:]
        if suffix.isdigit():
            highest = max(highest, int(suffix))
    return highest


def next_document_number(prefix, model, field, width=6):
    """Reserve and return the next number for `prefix`, e.g. 'INV-000042'."""
    from .models import DocumentSequence

    with transaction.atomic():
        seq = DocumentSequence.objects.select_for_update().filter(key=prefix).first()
        if seq is None:
            try:
                with transaction.atomic():
                    seq = DocumentSequence.objects.create(
                        key=prefix, next_value=_max_existing(model, field, prefix) + 1,
                    )
            except IntegrityError:
                pass  # another request created it first
            seq = DocumentSequence.objects.select_for_update().get(key=prefix)
        value = seq.next_value
        seq.next_value = value + 1
        seq.save(update_fields=['next_value'])
    return f'{prefix}-{value:0{width}d}'
