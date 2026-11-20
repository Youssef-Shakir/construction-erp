"""
Payment services - allocation of posted payments to invoices / bills.

All validation lives here (not in the view) so it is enforced no matter
which entry point creates an allocation.
"""
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.db import transaction

from apps.accounting.posting import PostingError
from .models import Payment, PaymentAllocation


def allocate_payment(payment: Payment, document, amount: Decimal) -> PaymentAllocation:
    """
    Allocate `amount` of a posted payment to a posted invoice or bill.

    Rules:
    - payment and document must both be posted
    - inbound payments settle customer invoices, outbound settle supplier bills
    - the document must belong to the same partner as the payment
    - amount > 0, <= payment's unallocated amount, <= document's remaining amount

    Both rows are locked so concurrent allocations can't over-allocate.
    """
    from apps.invoicing.models import Invoice, Bill

    if amount is None or amount <= 0:
        raise PostingError('المبلغ يجب أن يكون أكبر من صفر')

    with transaction.atomic():
        payment = Payment.objects.select_for_update().get(pk=payment.pk)
        doc_model = type(document)
        document = doc_model.objects.select_for_update().get(pk=document.pk)

        if payment.status != 'posted':
            raise PostingError('يجب ترحيل الدفعة أولاً')

        if payment.direction == 'inbound':
            if not isinstance(document, Invoice):
                raise PostingError('الدفعات الواردة تُخصص لفواتير العملاء فقط')
            doc_partner_id = document.customer_id
        else:
            if not isinstance(document, Bill):
                raise PostingError('الدفعات الصادرة تُخصص لفواتير الموردين فقط')
            doc_partner_id = document.supplier_id

        if document.status != 'posted':
            raise PostingError('لا يمكن التخصيص لمستند غير مرحّل')

        if doc_partner_id != payment.partner_id:
            raise PostingError('المستند يخص شريكاً مختلفاً عن شريك الدفعة')

        if amount > payment.unallocated_amount:
            raise PostingError(f'المبلغ يتجاوز غير المخصص من الدفعة ({payment.unallocated_amount})')

        if amount > document.amount_remaining:
            raise PostingError(f'المبلغ يتجاوز المتبقي في المستند ({document.amount_remaining})')

        return PaymentAllocation.objects.create(
            payment=payment,
            content_type=ContentType.objects.get_for_model(doc_model),
            object_id=document.pk,
            amount=amount,
        )
