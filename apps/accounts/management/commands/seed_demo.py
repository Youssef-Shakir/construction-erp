"""
Management command to seed demo data for the Construction ERP.
Creates sample accounts, journals, users, partners, projects, and documents.
"""
from decimal import Decimal
from datetime import date, timedelta
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

User = get_user_model()


class Command(BaseCommand):
    help = 'Seed database with demo data'

    def handle(self, *args, **options):
        self.stdout.write('Seeding demo data...')

        self.create_groups()
        self.create_users()
        self.create_account_types()
        self.create_accounts()
        self.create_journals()
        self.create_partners()
        self.create_projects()
        self.create_demo_documents()

        self.stdout.write(self.style.SUCCESS('Demo data seeded successfully!'))

    def create_groups(self):
        """Create permission groups."""
        self.stdout.write('  Creating groups...')
        Group.objects.get_or_create(name='BusinessManager')
        Group.objects.get_or_create(name='Accountant')
        Group.objects.get_or_create(name='DataEntry')

    def create_users(self):
        """Create sample users."""
        self.stdout.write('  Creating users...')

        # Business Manager
        if not User.objects.filter(email='admin@example.com').exists():
            admin = User.objects.create_superuser(
                email='admin@example.com',
                password='admin123',
                first_name='المدير',
                last_name='العام',
            )
            admin.groups.add(Group.objects.get(name='BusinessManager'))

        # Accountant
        if not User.objects.filter(email='accountant@example.com').exists():
            accountant = User.objects.create_user(
                email='accountant@example.com',
                password='accountant123',
                first_name='محاسب',
                last_name='الشركة',
            )
            accountant.groups.add(Group.objects.get(name='Accountant'))

        # Data Entry
        if not User.objects.filter(email='dataentry@example.com').exists():
            dataentry = User.objects.create_user(
                email='dataentry@example.com',
                password='dataentry123',
                first_name='موظف',
                last_name='الإدخال',
            )
            dataentry.groups.add(Group.objects.get(name='DataEntry'))

    def create_account_types(self):
        """Create account types."""
        self.stdout.write('  Creating account types...')
        from apps.accounting.models import AccountType

        types = [
            ('asset', 'الأصول', 'Assets', 1),
            ('liability', 'الخصوم', 'Liabilities', 2),
            ('equity', 'حقوق الملكية', 'Equity', 3),
            ('revenue', 'الإيرادات', 'Revenue', 4),
            ('expense', 'المصروفات', 'Expenses', 5),
        ]

        for code, name, name_en, order in types:
            AccountType.objects.get_or_create(
                code=code,
                defaults={'name': name, 'name_en': name_en, 'order': order}
            )

    def create_accounts(self):
        """Create chart of accounts."""
        self.stdout.write('  Creating accounts...')
        from apps.accounting.models import Account, AccountType

        accounts = [
            # Assets
            ('1000', 'النقدية', 'Cash', 'asset', False),
            ('1010', 'البنك', 'Bank', 'asset', False),
            ('1100', 'العملاء', 'Accounts Receivable', 'asset', True),
            ('1200', 'سلف الموظفين', 'Advances to Employees', 'asset', True),

            # Liabilities
            ('2000', 'الموردين', 'Accounts Payable', 'liability', True),
            ('2100', 'مستحقات أخرى', 'Other Payables', 'liability', False),

            # Equity
            ('3000', 'رأس المال', 'Capital', 'equity', False),
            ('3100', 'الأرباح المحتجزة', 'Retained Earnings', 'equity', False),

            # Revenue
            ('4000', 'إيرادات المشاريع', 'Project Revenue', 'revenue', False),
            ('4100', 'إيرادات أخرى', 'Other Revenue', 'revenue', False),

            # Expenses
            ('5000', 'مصروفات المواد', 'Materials', 'expense', False),
            ('5100', 'مصروفات العمالة', 'Labor', 'expense', False),
            ('5200', 'مصروفات المعدات', 'Equipment', 'expense', False),
            ('5300', 'مصروفات النقل', 'Transportation', 'expense', False),
            ('5400', 'مصروفات إدارية', 'Administrative', 'expense', False),
            ('5500', 'مصروفات أخرى', 'Other Expenses', 'expense', False),
        ]

        for code, name, name_en, type_code, is_control in accounts:
            account_type = AccountType.objects.get(code=type_code)
            Account.objects.get_or_create(
                code=code,
                defaults={
                    'name': name,
                    'name_en': name_en,
                    'account_type': account_type,
                    'is_control': is_control,
                }
            )

    def create_journals(self):
        """Create journals."""
        self.stdout.write('  Creating journals...')
        from apps.accounting.models import Journal

        journals = [
            ('GEN', 'القيود العامة', 'general'),
            ('CASH', 'يومية النقدية', 'cash'),
            ('BANK', 'يومية البنك', 'bank'),
            ('SALE', 'يومية المبيعات', 'sale'),
            ('PURCH', 'يومية المشتريات', 'purchase'),
        ]

        for code, name, journal_type in journals:
            Journal.objects.get_or_create(
                code=code,
                defaults={'name': name, 'type': journal_type}
            )

    def create_partners(self):
        """Create sample partners."""
        self.stdout.write('  Creating partners...')
        from apps.core.models import Partner

        # Customers
        customers = [
            ('CUST001', 'شركة البناء الحديث', 'customer'),
            ('CUST002', 'مؤسسة التطوير العقاري', 'customer'),
        ]

        for code, name, partner_type in customers:
            Partner.objects.get_or_create(
                code=code,
                defaults={'name': name, 'type': partner_type}
            )

        # Suppliers
        suppliers = [
            ('SUPP001', 'مصنع الأسمنت الوطني', 'supplier'),
            ('SUPP002', 'شركة الحديد المتحدة', 'supplier'),
            ('SUPP003', 'مؤسسة النقل السريع', 'supplier'),
        ]

        for code, name, partner_type in suppliers:
            Partner.objects.get_or_create(
                code=code,
                defaults={'name': name, 'type': partner_type}
            )

        # Employees
        employees = [
            ('EMP001', 'أحمد محمد', 'employee'),
            ('EMP002', 'خالد عبدالله', 'employee'),
        ]

        for code, name, partner_type in employees:
            Partner.objects.get_or_create(
                code=code,
                defaults={'name': name, 'type': partner_type}
            )

    def create_projects(self):
        """Create sample projects."""
        self.stdout.write('  Creating projects...')
        from apps.projects.models import Project
        from apps.core.models import Partner

        customer1 = Partner.objects.get(code='CUST001')
        customer2 = Partner.objects.get(code='CUST002')

        projects = [
            ('PRJ001', 'مشروع برج السكني', customer1, date.today() - timedelta(days=30), Decimal('500000')),
            ('PRJ002', 'مجمع المكاتب التجارية', customer2, date.today() - timedelta(days=15), Decimal('750000')),
        ]

        for code, name, customer, start, budget in projects:
            Project.objects.get_or_create(
                code=code,
                defaults={
                    'name': name,
                    'customer': customer,
                    'start_date': start,
                    'budget': budget,
                    'status': 'active',
                }
            )

    def create_demo_documents(self):
        """Create sample invoices and bills."""
        self.stdout.write('  Creating sample documents...')
        from apps.projects.models import Project
        from apps.core.models import Partner
        from apps.invoicing.models import Invoice, Bill
        from apps.accounting.models import Account

        project1 = Project.objects.get(code='PRJ001')
        project2 = Project.objects.get(code='PRJ002')
        customer1 = Partner.objects.get(code='CUST001')
        supplier1 = Partner.objects.get(code='SUPP001')
        expense_account = Account.objects.get(code='5000')

        # Create a sample invoice
        Invoice.objects.get_or_create(
            invoice_number='INV-000001',
            defaults={
                'project': project1,
                'customer': customer1,
                'date': date.today() - timedelta(days=10),
                'due_date': date.today() + timedelta(days=20),
                'amount': Decimal('50000'),
                'amount_base': Decimal('50000'),
                'description': 'دفعة أولى لمشروع البرج السكني',
                'status': 'draft',
            }
        )

        # Create a sample bill
        Bill.objects.get_or_create(
            bill_number='BILL-000001',
            defaults={
                'project': project1,
                'supplier': supplier1,
                'account': expense_account,
                'date': date.today() - timedelta(days=5),
                'due_date': date.today() + timedelta(days=25),
                'amount': Decimal('15000'),
                'amount_base': Decimal('15000'),
                'description': 'توريد مواد بناء',
                'status': 'draft',
            }
        )

        self.stdout.write('  Demo documents created (as drafts - post manually to test)')
