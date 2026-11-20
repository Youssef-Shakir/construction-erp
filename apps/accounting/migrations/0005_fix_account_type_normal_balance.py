"""
Repair AccountType rows created by the old seed_demo, which left
normal_balance / report_section blank. With a blank normal_balance every
asset and expense account was treated as credit-normal, flipping the sign
of their balances in every report.
"""
from django.db import migrations

STANDARD = {
    'asset': ('debit', 'balance_sheet'),
    'liability': ('credit', 'balance_sheet'),
    'equity': ('credit', 'balance_sheet'),
    'revenue': ('credit', 'income_statement'),
    'expense': ('debit', 'income_statement'),
}


def forwards(apps, schema_editor):
    AccountType = apps.get_model('accounting', 'AccountType')
    for code, (normal_balance, section) in STANDARD.items():
        AccountType.objects.filter(code=code, normal_balance='').update(normal_balance=normal_balance)
        AccountType.objects.filter(code=code, report_section='').update(report_section=section)


class Migration(migrations.Migration):
    dependencies = [('accounting', '0004_alter_account_parent')]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
