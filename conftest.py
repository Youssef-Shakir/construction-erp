"""
Pytest configuration for Construction ERP.
"""
import pytest
from django.contrib.auth import get_user_model

User = get_user_model()


@pytest.fixture
def business_manager(db):
    """Create a business manager user."""
    from django.contrib.auth.models import Group
    user = User.objects.create_user(
        email='manager@example.com',
        password='testpass123',
        first_name='مدير',
        last_name='الأعمال',
    )
    group, _ = Group.objects.get_or_create(name='BusinessManager')
    user.groups.add(group)
    return user


@pytest.fixture
def accountant(db):
    """Create an accountant user."""
    from django.contrib.auth.models import Group
    user = User.objects.create_user(
        email='accountant@example.com',
        password='testpass123',
        first_name='محاسب',
        last_name='الشركة',
    )
    group, _ = Group.objects.get_or_create(name='Accountant')
    user.groups.add(group)
    return user


@pytest.fixture
def data_entry(db):
    """Create a data entry user."""
    from django.contrib.auth.models import Group
    user = User.objects.create_user(
        email='dataentry@example.com',
        password='testpass123',
        first_name='مدخل',
        last_name='البيانات',
    )
    group, _ = Group.objects.get_or_create(name='DataEntry')
    user.groups.add(group)
    return user


@pytest.fixture
def client_logged_in(client, business_manager):
    """Return a logged-in test client."""
    client.force_login(business_manager)
    return client
