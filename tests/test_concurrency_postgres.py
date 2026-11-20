"""
Real concurrency tests: two threads post at the same moment.

Only meaningful on PostgreSQL (SQLite has no row locks), so they are skipped
elsewhere. Run them with:  docker compose --profile test run --rm test
"""
import threading
from datetime import date
from decimal import Decimal

import pytest
from django.db import close_old_connections, connection

from apps.accounting.models import JournalEntry
from apps.accounting.posting import PostingError
from apps.advances.models import CashAdvance
from apps.expenses.models import Expense

from tests.test_journal_rules import (  # noqa: F401
    account_types, accounts, journals, customer, supplier, employee, project,
)

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def postgres_only():
    if connection.vendor != 'postgresql':
        pytest.skip('row-lock tests need PostgreSQL')


def _race(*callables):
    """Run callables simultaneously; return list of results/exceptions."""
    barrier = threading.Barrier(len(callables))
    results = [None] * len(callables)

    def run(i, fn):
        try:
            barrier.wait()
            results[i] = fn()
        except Exception as exc:  # noqa: BLE001 - collected for assertions
            results[i] = exc
        finally:
            close_old_connections()

    threads = [threading.Thread(target=run, args=(i, fn)) for i, fn in enumerate(callables)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    return results


def test_double_click_post_creates_one_entry(accounts, journals, employee, project):
    adv = CashAdvance.objects.create(project=project, recipient=employee, date=date(2026, 1, 1),
                                     purpose='x', amount=Decimal('1000'))
    pk = adv.pk
    results = _race(
        lambda: CashAdvance.objects.get(pk=pk).post(),
        lambda: CashAdvance.objects.get(pk=pk).post(),
    )
    errors = [r for r in results if isinstance(r, Exception)]
    assert len(errors) == 1 and isinstance(errors[0], PostingError), results
    assert JournalEntry.objects.filter(reference=adv.advance_number).count() == 1


def test_two_expenses_cannot_overspend_advance(accounts, journals, employee, project):
    adv = CashAdvance.objects.create(project=project, recipient=employee, date=date(2026, 1, 1),
                                     purpose='x', amount=Decimal('1000'))
    adv.post()
    e1, e2 = (
        Expense.objects.create(date=date(2026, 1, 2), advance=adv, project=project,
                               account=accounts['expense'], description=f'e{i}', amount=Decimal('700'))
        for i in (1, 2)
    )
    results = _race(
        lambda: Expense.objects.get(pk=e1.pk).post(),
        lambda: Expense.objects.get(pk=e2.pk).post(),
    )
    errors = [r for r in results if isinstance(r, Exception)]
    assert len(errors) == 1 and isinstance(errors[0], PostingError), results
    assert CashAdvance.objects.get(pk=adv.pk).remaining == Decimal('300')
