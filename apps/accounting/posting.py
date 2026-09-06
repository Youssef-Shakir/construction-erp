"""
Posting engine for journal entries.

This module provides the core functionality for creating and posting
journal entries atomically, with validation that debits == credits.
"""
from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError

from .models import Journal, JournalEntry, JournalLine, Account


class PostingError(Exception):
    """Raised when posting validation fails."""
    pass


def create_journal_entry(
    journal: Journal,
    date,
    lines: list,
    reference: str = '',
    memo: str = '',
    user=None,
    auto_post: bool = True,
) -> JournalEntry:
    """
    Create a journal entry with the given lines.

    Args:
        journal: The Journal to post to
        date: Entry date
        lines: List of dicts with keys:
            - account: Account instance or account code
            - debit: Decimal amount (default 0)
            - credit: Decimal amount (default 0)
            - description: Optional line description
            - partner: Optional Partner instance
            - project: Optional Project instance
        reference: Document reference (e.g., "INV-000001")
        memo: Entry description/memo
        user: User creating the entry
        auto_post: If True, post immediately after creation

    Returns:
        JournalEntry instance

    Raises:
        PostingError: If validation fails
    """
    if len(lines) < 2:
        raise PostingError('القيد يجب أن يحتوي على سطرين على الأقل')

    # Calculate totals
    total_debit = Decimal('0.00')
    total_credit = Decimal('0.00')

    for line in lines:
        debit = line.get('debit', Decimal('0.00'))
        credit = line.get('credit', Decimal('0.00'))

        if not isinstance(debit, Decimal):
            debit = Decimal(str(debit))
        if not isinstance(credit, Decimal):
            credit = Decimal(str(credit))

        total_debit += debit
        total_credit += credit

    # Validate balance
    if total_debit != total_credit:
        raise PostingError(
            f'القيد غير متوازن: مدين {total_debit} != دائن {total_credit}'
        )

    if total_debit == 0:
        raise PostingError('مجموع القيد لا يمكن أن يكون صفراً')

    with transaction.atomic():
        # Create entry
        entry = JournalEntry.objects.create(
            journal=journal,
            entry_number=journal.get_next_entry_number(),
            date=date,
            reference=reference,
            memo=memo,
            created_by=user,
        )

        # Create lines
        for i, line_data in enumerate(lines, start=1):
            account = line_data['account']
            if isinstance(account, str):
                account = Account.objects.get(code=account)

            debit = line_data.get('debit', Decimal('0.00'))
            credit = line_data.get('credit', Decimal('0.00'))

            if not isinstance(debit, Decimal):
                debit = Decimal(str(debit))
            if not isinstance(credit, Decimal):
                credit = Decimal(str(credit))

            # Skip zero lines
            if debit == 0 and credit == 0:
                continue

            line = JournalLine(
                entry=entry,
                line_number=i,
                account=account,
                description=line_data.get('description', ''),
                debit=debit,
                credit=credit,
                partner=line_data.get('partner'),
                project=line_data.get('project'),
            )

            # Validate line
            try:
                line.clean()
            except ValidationError as e:
                raise PostingError(str(e))

            line.save()

        # Post if requested
        if auto_post:
            post_entry(entry, user)

    return entry


def post_entry(entry: JournalEntry, user=None) -> None:
    """
    Post a journal entry (mark as posted).

    Args:
        entry: JournalEntry to post
        user: User posting the entry

    Raises:
        PostingError: If entry is already posted or unbalanced
    """
    if entry.is_posted:
        raise PostingError('القيد مرحّل بالفعل')

    if not entry.is_balanced:
        raise PostingError('القيد غير متوازن')

    if entry.lines.count() < 2:
        raise PostingError('القيد يجب أن يحتوي على سطرين على الأقل')

    entry.is_posted = True
    entry.posted_at = timezone.now()
    entry.posted_by = user
    entry.save()


def reverse_entry(entry: JournalEntry, date, user=None, memo: str = '') -> JournalEntry:
    """
    Create a reversal entry for an existing posted entry.

    Args:
        entry: JournalEntry to reverse
        date: Date for the reversal entry
        user: User creating the reversal
        memo: Optional memo for reversal

    Returns:
        New JournalEntry that reverses the original

    Raises:
        PostingError: If entry is not posted or already reversed
    """
    if not entry.is_posted:
        raise PostingError('لا يمكن إلغاء قيد غير مرحّل')

    if entry.is_reversed:
        raise PostingError('القيد ملغي بالفعل')

    with transaction.atomic():
        # Create reversal lines (swap debits and credits)
        reversal_lines = []
        for line in entry.lines.all():
            reversal_lines.append({
                'account': line.account,
                'debit': line.credit,  # Swap
                'credit': line.debit,  # Swap
                'description': f'إلغاء: {line.description}' if line.description else 'إلغاء',
                'partner': line.partner,
                'project': line.project,
            })

        # Create reversal entry
        reversal = create_journal_entry(
            journal=entry.journal,
            date=date,
            lines=reversal_lines,
            reference=f'REV-{entry.entry_number}',
            memo=memo or f'إلغاء القيد {entry.entry_number}',
            user=user,
            auto_post=True,
        )

        # Link entries
        reversal.reverses = entry
        reversal.save()

        entry.is_reversed = True
        entry.reversed_by = reversal
        entry.save()

    return reversal


def get_account_balance(account: Account, as_of_date=None) -> Decimal:
    """
    Get the balance of an account.

    Args:
        account: Account to get balance for
        as_of_date: Optional date to get balance as of

    Returns:
        Decimal balance (positive for normal balance, negative for opposite)
    """
    if as_of_date:
        return account.get_balance_at_date(as_of_date)
    return account.balance


def get_trial_balance(as_of_date=None) -> list:
    """
    Generate trial balance - all accounts with their debit/credit balances.

    Args:
        as_of_date: Optional date for point-in-time balance

    Returns:
        List of dicts with account info and balances
    """
    from django.db.models import Sum, Q

    accounts = Account.objects.filter(is_active=True).select_related('account_type')

    result = []
    total_debit = Decimal('0.00')
    total_credit = Decimal('0.00')

    for account in accounts:
        # Build query
        query = Q(entry__is_posted=True)
        if as_of_date:
            query &= Q(entry__date__lte=as_of_date)

        # Get totals
        totals = account.journal_lines.filter(query).aggregate(
            debit_sum=Sum('debit'),
            credit_sum=Sum('credit')
        )

        debit = totals['debit_sum'] or Decimal('0.00')
        credit = totals['credit_sum'] or Decimal('0.00')

        # Calculate balance based on normal balance
        if account.account_type.normal_balance == 'debit':
            balance = debit - credit
            if balance > 0:
                debit_balance = balance
                credit_balance = Decimal('0.00')
            else:
                debit_balance = Decimal('0.00')
                credit_balance = abs(balance)
        else:
            balance = credit - debit
            if balance > 0:
                debit_balance = Decimal('0.00')
                credit_balance = balance
            else:
                debit_balance = abs(balance)
                credit_balance = Decimal('0.00')

        # Only include accounts with activity
        if debit_balance > 0 or credit_balance > 0:
            result.append({
                'account': account,
                'debit': debit_balance,
                'credit': credit_balance,
            })
            total_debit += debit_balance
            total_credit += credit_balance

    return {
        'accounts': result,
        'total_debit': total_debit,
        'total_credit': total_credit,
        'is_balanced': total_debit == total_credit,
    }
