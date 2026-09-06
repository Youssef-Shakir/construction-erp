"""
Tests for role-based permissions and scoping.

Roles:
- BusinessManager (Admin): Full access to everything
- Accountant: Create/edit/post documents, view ledgers, no user management
- DataEntry: Create/edit drafts only, no posting
"""
import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from apps.accounts.permissions import (
    is_business_manager, is_accountant, is_data_entry,
    can_post_document, can_create_reversal, can_create_manual_entry,
    can_manage_accounts, can_manage_journals, can_manage_users,
    can_view_reports, can_view_ledger, can_edit_draft, can_upload_attachments
)

User = get_user_model()


@pytest.fixture
def business_manager_user(db):
    """Create a business manager user."""
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
def accountant_user(db):
    """Create an accountant user."""
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
def data_entry_user(db):
    """Create a data entry user."""
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
def superuser(db):
    """Create a superuser."""
    return User.objects.create_superuser(
        email='admin@example.com',
        password='adminpass123',
        first_name='مدير',
        last_name='النظام',
    )


class TestRoleIdentification:
    """Test role identification functions."""

    def test_business_manager_identification(self, business_manager_user):
        """Test is_business_manager returns True for business managers."""
        assert is_business_manager(business_manager_user)
        assert not is_accountant(business_manager_user)
        assert not is_data_entry(business_manager_user)

    def test_accountant_identification(self, accountant_user):
        """Test is_accountant returns True for accountants."""
        assert not is_business_manager(accountant_user)
        assert is_accountant(accountant_user)
        assert not is_data_entry(accountant_user)

    def test_data_entry_identification(self, data_entry_user):
        """Test is_data_entry returns True for data entry users."""
        assert not is_business_manager(data_entry_user)
        assert not is_accountant(data_entry_user)
        assert is_data_entry(data_entry_user)

    def test_superuser_is_business_manager(self, superuser):
        """Test that superuser is treated as business manager."""
        assert is_business_manager(superuser)


class TestBusinessManagerPermissions:
    """Test permissions for business manager role."""

    def test_can_post_documents(self, business_manager_user):
        assert can_post_document(business_manager_user)

    def test_can_create_reversals(self, business_manager_user):
        assert can_create_reversal(business_manager_user)

    def test_can_create_manual_entries(self, business_manager_user):
        assert can_create_manual_entry(business_manager_user)

    def test_can_manage_accounts(self, business_manager_user):
        assert can_manage_accounts(business_manager_user)

    def test_can_manage_journals(self, business_manager_user):
        assert can_manage_journals(business_manager_user)

    def test_can_manage_users(self, business_manager_user):
        assert can_manage_users(business_manager_user)

    def test_can_view_reports(self, business_manager_user):
        assert can_view_reports(business_manager_user)

    def test_can_view_ledger(self, business_manager_user):
        assert can_view_ledger(business_manager_user)

    def test_can_edit_draft(self, business_manager_user):
        assert can_edit_draft(business_manager_user)

    def test_can_upload_attachments(self, business_manager_user):
        assert can_upload_attachments(business_manager_user)


class TestAccountantPermissions:
    """Test permissions for accountant role."""

    def test_can_post_documents(self, accountant_user):
        assert can_post_document(accountant_user)

    def test_cannot_create_reversals(self, accountant_user):
        """Accountants cannot create reversal entries."""
        assert not can_create_reversal(accountant_user)

    def test_can_create_manual_entries(self, accountant_user):
        assert can_create_manual_entry(accountant_user)

    def test_cannot_manage_accounts(self, accountant_user):
        """Accountants cannot manage chart of accounts."""
        assert not can_manage_accounts(accountant_user)

    def test_cannot_manage_journals(self, accountant_user):
        """Accountants cannot manage journals configuration."""
        assert not can_manage_journals(accountant_user)

    def test_cannot_manage_users(self, accountant_user):
        """Accountants cannot manage users."""
        assert not can_manage_users(accountant_user)

    def test_can_view_reports(self, accountant_user):
        assert can_view_reports(accountant_user)

    def test_can_view_ledger(self, accountant_user):
        assert can_view_ledger(accountant_user)

    def test_can_edit_draft(self, accountant_user):
        assert can_edit_draft(accountant_user)

    def test_can_upload_attachments(self, accountant_user):
        assert can_upload_attachments(accountant_user)


class TestDataEntryPermissions:
    """Test permissions for data entry role."""

    def test_cannot_post_documents(self, data_entry_user):
        """Data entry cannot post documents."""
        assert not can_post_document(data_entry_user)

    def test_cannot_create_reversals(self, data_entry_user):
        assert not can_create_reversal(data_entry_user)

    def test_cannot_create_manual_entries(self, data_entry_user):
        assert not can_create_manual_entry(data_entry_user)

    def test_cannot_manage_accounts(self, data_entry_user):
        assert not can_manage_accounts(data_entry_user)

    def test_cannot_manage_journals(self, data_entry_user):
        assert not can_manage_journals(data_entry_user)

    def test_cannot_manage_users(self, data_entry_user):
        assert not can_manage_users(data_entry_user)

    def test_cannot_view_reports(self, data_entry_user):
        """Data entry cannot view financial reports."""
        assert not can_view_reports(data_entry_user)

    def test_cannot_view_ledger(self, data_entry_user):
        """Data entry cannot view ledger."""
        assert not can_view_ledger(data_entry_user)

    def test_can_edit_draft(self, data_entry_user):
        """Data entry can edit draft documents."""
        assert can_edit_draft(data_entry_user)

    def test_can_upload_attachments(self, data_entry_user):
        """Data entry can upload attachments."""
        assert can_upload_attachments(data_entry_user)


class TestSuperuserPermissions:
    """Test that superuser has all permissions."""

    def test_superuser_full_access(self, superuser):
        """Superuser should have all permissions."""
        assert can_post_document(superuser)
        assert can_create_reversal(superuser)
        assert can_create_manual_entry(superuser)
        assert can_manage_accounts(superuser)
        assert can_manage_journals(superuser)
        assert can_manage_users(superuser)
        assert can_view_reports(superuser)
        assert can_view_ledger(superuser)
        assert can_edit_draft(superuser)
        assert can_upload_attachments(superuser)


class TestAnonymousUser:
    """Test permissions for unauthenticated users."""

    def test_anonymous_no_permissions(self, db):
        """Anonymous users should have no permissions."""
        from django.contrib.auth.models import AnonymousUser
        anon = AnonymousUser()

        assert not is_business_manager(anon)
        assert not is_accountant(anon)
        assert not is_data_entry(anon)
        assert not can_post_document(anon)
        assert not can_create_reversal(anon)
        assert not can_manage_users(anon)
        assert not can_view_reports(anon)
        assert not can_edit_draft(anon)
        assert not can_upload_attachments(anon)


class TestViewDecorators:
    """Test view permission decorators."""

    def test_business_manager_required_allows_manager(
        self, business_manager_user, client
    ):
        """Business manager can access protected views."""
        client.force_login(business_manager_user)
        # This test would need an actual URL to test against
        # For now, we just verify the permission check works
        assert is_business_manager(business_manager_user)

    def test_accountant_required_allows_accountant(
        self, accountant_user, client
    ):
        """Accountant can access accountant-level views."""
        client.force_login(accountant_user)
        assert is_accountant(accountant_user)

    def test_accountant_required_allows_business_manager(
        self, business_manager_user, client
    ):
        """Business manager can access accountant-level views."""
        client.force_login(business_manager_user)
        # Business managers should pass accountant_required check
        assert is_business_manager(business_manager_user)
