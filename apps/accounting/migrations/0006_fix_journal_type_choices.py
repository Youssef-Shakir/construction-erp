"""
seed_demo created journals with type 'sale' / 'purchase', which are not valid
choices ('sales' / 'purchases'): those journals could not be edited in the UI.
"""
from django.db import migrations


def forwards(apps, schema_editor):
    Journal = apps.get_model('accounting', 'Journal')
    Journal.objects.filter(type='sale').update(type='sales')
    Journal.objects.filter(type='purchase').update(type='purchases')


class Migration(migrations.Migration):
    dependencies = [('accounting', '0005_fix_account_type_normal_balance')]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
