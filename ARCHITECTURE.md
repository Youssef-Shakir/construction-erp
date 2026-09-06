# Architecture Review — Construction ERP V1

This document details the technical architecture derived from CLAUDE.md, including the full database schema, document lifecycles, posting engine design, permission model, and screen inventory.

---

## 0. Language & Localization

**Primary Language:** Arabic (RTL)

- All UI text in Arabic
- RTL (right-to-left) layout throughout
- Django i18n with `LANGUAGE_CODE = 'ar'`
- Tailwind CSS RTL support via `dir="rtl"` on `<html>`
- Numbers remain LTR (standard for accounting)
- Date format: `YYYY-MM-DD` (ISO) or localized Arabic
- Currency: Configurable (default: local currency)

---

## 1. Database Schema

### 1.1 `core` App

```
CompanySettings (singleton)
├── name: CharField(255)
├── currency: CharField(3) default='PHP'  # or local currency
├── fiscal_year_start: DateField
├── address: TextField (nullable)
├── created_at: DateTimeField(auto_now_add)
├── updated_at: DateTimeField(auto_now)
```

```
Partner
├── id: BigAutoField (PK)
├── code: CharField(20) unique
├── name: CharField(255)
├── type: CharField choices=['customer','supplier','employee']  # see Issue #1
├── email: EmailField (nullable)
├── phone: CharField(50) (nullable)
├── address: TextField (nullable)
├── is_active: BooleanField default=True
├── user: OneToOneField(User) (nullable)  # links to User for employees
├── created_at, updated_at, created_by, updated_by (audit mixin)
├── history: HistoricalRecords()
```

```
Attachment
├── id: BigAutoField (PK)
├── content_type: ForeignKey(ContentType)
├── object_id: PositiveIntegerField
├── content_object: GenericForeignKey('content_type', 'object_id')
├── file: FileField(upload_to=dynamic_path)  # MEDIA_ROOT/<app>/<model>/<id>/
├── original_filename: CharField(255)
├── uploaded_by: ForeignKey(User)
├── uploaded_at: DateTimeField(auto_now_add)
├── description: CharField(255) (nullable)
```

### 1.2 `accounts` App

```
User (AbstractUser)
├── id: BigAutoField (PK)
├── email: EmailField unique (used as username)
├── first_name, last_name: CharField
├── is_active, is_staff, is_superuser: BooleanField
├── date_joined: DateTimeField
├── groups: ManyToManyField(Group)  # Admin, Accounting, ProjectManager
├── history: HistoricalRecords()
```

Groups (Django built-in, seeded):
- `Admin`
- `Accounting`
- `ProjectManager`

### 1.3 `projects` App

```
Project
├── id: BigAutoField (PK)
├── code: CharField(20) unique
├── name: CharField(255)
├── customer: ForeignKey(Partner) limit_to={'type': 'customer'}
├── status: CharField choices=['active','completed','on_hold','cancelled']
├── start_date: DateField (nullable)
├── end_date: DateField (nullable)
├── budget: DecimalField(18,2) (nullable)
├── description: TextField (nullable)
├── created_at, updated_at, created_by, updated_by
├── history: HistoricalRecords()
```

### 1.4 `accounting` App

```
AccountType
├── id: BigAutoField (PK)
├── code: CharField(20) unique  # 'asset','liability','equity','revenue','expense'
├── name: CharField(100)
├── normal_balance: CharField choices=['debit','credit']
├── report_section: CharField choices=['balance_sheet','income_statement']
```

```
Account
├── id: BigAutoField (PK)
├── code: CharField(20) unique
├── name: CharField(255)
├── account_type: ForeignKey(AccountType)
├── parent: ForeignKey('self') (nullable) related_name='children'
├── is_control: BooleanField default=False  # AR, AP, Advances to PMs
├── is_active: BooleanField default=True
├── description: TextField (nullable)
├── created_at, updated_at
├── history: HistoricalRecords()
```

```
Journal
├── id: BigAutoField (PK)
├── code: CharField(20) unique
├── name: CharField(100)
├── type: CharField choices=['cash','bank','sales','purchases','general']
├── default_debit_account: ForeignKey(Account) (nullable)
├── default_credit_account: ForeignKey(Account) (nullable)
├── is_active: BooleanField default=True
├── created_at, updated_at
```

```
JournalEntry
├── id: BigAutoField (PK)
├── journal: ForeignKey(Journal)
├── entry_number: CharField(50) unique  # auto-generated per journal
├── date: DateField
├── reference: CharField(100) (nullable)  # links back to source document
├── memo: TextField (nullable)
├── is_posted: BooleanField default=False
├── is_reversed: BooleanField default=False
├── reversed_by: ForeignKey('self') (nullable)
├── reverses: ForeignKey('self') (nullable)  # if this is a reversal
├── posted_at: DateTimeField (nullable)
├── posted_by: ForeignKey(User) (nullable)
├── created_at, updated_at, created_by
├── history: HistoricalRecords()

Constraints:
- Sum of debits must equal sum of credits (enforced in posting engine)
- Once posted, entry is immutable
```

```
JournalLine
├── id: BigAutoField (PK)
├── entry: ForeignKey(JournalEntry) related_name='lines'
├── line_number: PositiveIntegerField
├── account: ForeignKey(Account)
├── description: CharField(255) (nullable)
├── debit: DecimalField(18,2) default=0
├── credit: DecimalField(18,2) default=0
├── partner: ForeignKey(Partner) (nullable)  # for AR/AP/Advances tracking
├── project: ForeignKey(Project) (nullable)  # for project-level reporting
├── created_at: DateTimeField(auto_now_add)

Constraints:
- Either debit > 0 OR credit > 0, never both
- If account.is_control and account is AR/AP/Advances, partner is required
```

### 1.5 `advances` App

```
CashAdvance
├── id: BigAutoField (PK)
├── advance_number: CharField(50) unique  # auto-generated
├── project: ForeignKey(Project)  # required
├── recipient: ForeignKey(Partner) limit_to={'type': 'employee'}
├── date: DateField
├── purpose: TextField
├── amount: DecimalField(18,2)
├── currency: CharField(3) default='PHP'
├── amount_base: DecimalField(18,2)  # same as amount in V1
├── status: CharField choices=['draft','posted','closed','cancelled']
├── journal_entry: OneToOneField(JournalEntry) (nullable)
├── created_at, updated_at, created_by, updated_by
├── history: HistoricalRecords()

Derived fields (computed, not stored):
- total_expenses: Sum of related Expense amounts where posted
- total_returned: Sum of related AdvanceReturn amounts where posted
- remaining: amount - total_expenses - total_returned
- is_settled: remaining == 0 and status == 'closed'
```

```
AdvanceReturn
├── id: BigAutoField (PK)
├── return_number: CharField(50) unique
├── advance: ForeignKey(CashAdvance) related_name='returns'
├── date: DateField
├── amount: DecimalField(18,2)
├── currency: CharField(3) default='PHP'
├── amount_base: DecimalField(18,2)
├── notes: TextField (nullable)
├── status: CharField choices=['draft','posted','cancelled']
├── journal_entry: OneToOneField(JournalEntry) (nullable)
├── created_at, updated_at, created_by, updated_by
├── history: HistoricalRecords()
```

### 1.6 `expenses` App

```
Expense
├── id: BigAutoField (PK)
├── expense_number: CharField(50) unique
├── date: DateField
├── project: ForeignKey(Project) (nullable)  # null = company expense
├── advance: ForeignKey(CashAdvance) (nullable)  # if linked to advance
├── account: ForeignKey(Account) limit_to={'account_type__code': 'expense'}
├── partner: ForeignKey(Partner) (nullable)  # vendor/supplier
├── description: TextField
├── amount: DecimalField(18,2)
├── currency: CharField(3) default='PHP'
├── amount_base: DecimalField(18,2)
├── status: CharField choices=['draft','posted','cancelled']
├── journal_entry: OneToOneField(JournalEntry) (nullable)
├── created_at, updated_at, created_by, updated_by
├── history: HistoricalRecords()

Business rules:
- If advance is set, project must match advance.project
- If advance is set: credits Advances to PMs
- If advance is null: credits Cash/Bank (direct expense)
```

```
PaperReceipt
├── id: BigAutoField (PK)
├── receipt_number: CharField(50) unique
├── expense: ForeignKey(Expense) (nullable) related_name='receipts'
├── vendor_name: CharField(255)
├── date: DateField
├── amount: DecimalField(18,2)
├── description: CharField(255) (nullable)
├── received_from: ForeignKey(User)  # the PM who submitted it
├── received_at: DateTimeField(auto_now_add)
├── matched: BooleanField default=False  # linked to expense
├── notes: TextField (nullable)
├── created_at, updated_at
```

### 1.7 `invoicing` App

```
Invoice
├── id: BigAutoField (PK)
├── invoice_number: CharField(50) unique
├── project: ForeignKey(Project)  # required
├── customer: ForeignKey(Partner) limit_to={'type': 'customer'}
├── date: DateField
├── due_date: DateField
├── description: TextField
├── amount: DecimalField(18,2)
├── currency: CharField(3) default='PHP'
├── amount_base: DecimalField(18,2)
├── status: CharField choices=['draft','posted','cancelled']
├── journal_entry: OneToOneField(JournalEntry) (nullable)
├── created_at, updated_at, created_by, updated_by
├── history: HistoricalRecords()

Derived fields (computed):
- amount_paid: Sum of PaymentAllocation amounts
- amount_remaining: amount - amount_paid
- is_paid: amount_remaining == 0
- is_overdue: not is_paid and due_date < today
```

```
Bill
├── id: BigAutoField (PK)
├── bill_number: CharField(50) unique
├── project: ForeignKey(Project) (nullable)  # null = company-level
├── supplier: ForeignKey(Partner) limit_to={'type': 'supplier'}
├── vendor_reference: CharField(100) (nullable)  # supplier's invoice number
├── date: DateField
├── due_date: DateField
├── account: ForeignKey(Account) limit_to={'account_type__code': 'expense'}
├── description: TextField
├── amount: DecimalField(18,2)
├── currency: CharField(3) default='PHP'
├── amount_base: DecimalField(18,2)
├── status: CharField choices=['draft','posted','cancelled']
├── journal_entry: OneToOneField(JournalEntry) (nullable)
├── created_at, updated_at, created_by, updated_by
├── history: HistoricalRecords()

Derived fields (computed):
- amount_paid: Sum of PaymentAllocation amounts
- amount_remaining: amount - amount_paid
- is_paid: amount_remaining == 0
- is_overdue: not is_paid and due_date < today
```

### 1.8 `payments` App

```
Payment
├── id: BigAutoField (PK)
├── payment_number: CharField(50) unique
├── direction: CharField choices=['inbound','outbound']
├── partner: ForeignKey(Partner)
├── date: DateField
├── account: ForeignKey(Account)  # Cash or Bank account
├── amount: DecimalField(18,2)
├── currency: CharField(3) default='PHP'
├── amount_base: DecimalField(18,2)
├── reference: CharField(100) (nullable)  # check number, transfer ref
├── memo: TextField (nullable)
├── status: CharField choices=['draft','posted','cancelled']
├── journal_entry: OneToOneField(JournalEntry) (nullable)
├── created_at, updated_at, created_by, updated_by
├── history: HistoricalRecords()

Derived:
- allocated_amount: Sum of allocations
- unallocated_amount: amount - allocated_amount
```

```
PaymentAllocation
├── id: BigAutoField (PK)
├── payment: ForeignKey(Payment) related_name='allocations'
├── content_type: ForeignKey(ContentType)  # Invoice or Bill
├── object_id: PositiveIntegerField
├── document: GenericForeignKey('content_type', 'object_id')
├── amount: DecimalField(18,2)
├── created_at: DateTimeField(auto_now_add)

Constraints:
- Sum of allocations for a payment <= payment.amount
- Sum of allocations for an invoice/bill <= document.amount
- Inbound payments allocate to Invoices only
- Outbound payments allocate to Bills only
```

### 1.9 `dashboard` App

No models. Views only, aggregating data from other apps.

---

## 2. Transaction Lifecycle per Document

All documents follow a consistent state machine:

```
┌─────────┐      post()       ┌─────────┐     reverse()     ┌───────────┐
│  DRAFT  │ ───────────────▶  │ POSTED  │ ────────────────▶ │ CANCELLED │
└─────────┘                   └─────────┘                   └───────────┘
     │                              │
     │ delete()                     │ (immutable)
     ▼                              │
  (removed)                         ▼
                              Cannot edit
```

### 2.1 State Definitions

| State     | Journal Entry | Editable | Deletable |
|-----------|---------------|----------|-----------|
| draft     | None          | Yes      | Yes       |
| submitted | None          | Limited* | Yes       |
| posted    | Created       | No       | No        |
| cancelled | Reversed      | No       | No        |
| closed    | N/A (advance) | No       | No        |

*Submitted expenses: Accounting can edit before posting; PM cannot edit after submission.

### 2.2 Document-Specific Lifecycles

**CashAdvance:**
```
draft → posted → closed
              ↘ cancelled (via reversal)
```
- Closed when: remaining balance = 0 (all expenses and returns accounted)
- Closing is a manual action by Accounting after settlement

**Expense:**
```
draft → posted → cancelled
submitted → posted → cancelled  (PM flow)
```
- PM submits → Accounting reviews → Accounting posts

**Invoice / Bill:**
```
draft → posted → cancelled
```
- Payment status is derived, not a state

**Payment:**
```
draft → posted → cancelled
```
- Allocations created after posting

**AdvanceReturn:**
```
draft → posted → cancelled
```

---

## 3. Posting Engine Design

### 3.1 Location

`accounting/posting.py`

### 3.2 Core Functions

```python
def create_journal_entry(
    journal: Journal,
    date: date,
    lines: list[dict],  # [{account, debit, credit, partner?, project?, description?}]
    reference: str = None,
    memo: str = None,
    user: User = None,
) -> JournalEntry:
    """
    Creates and posts a journal entry atomically.

    Validates:
    - At least 2 lines
    - Sum(debits) == Sum(credits)
    - Each line has debit XOR credit > 0
    - Control accounts have partner set

    Raises:
    - PostingError if validation fails
    """

def reverse_entry(
    entry: JournalEntry,
    date: date,
    user: User,
) -> JournalEntry:
    """
    Creates a reversal entry with debits/credits swapped.
    Links original.reversed_by to new entry.
    Links new entry.reverses to original.
    Marks original.is_reversed = True.
    """

def validate_entry(entry: JournalEntry) -> None:
    """
    Validates debits == credits, control account rules, etc.
    Called before posting.
    """
```

### 3.3 Document Posting (per app)

Each document model has a `post()` method:

```python
# Example: CashAdvance.post()
def post(self, user: User) -> None:
    with transaction.atomic():
        if self.status != 'draft':
            raise PostingError("Can only post draft documents")

        lines = [
            {
                'account': Account.objects.get(code='ADVANCES_PM'),
                'debit': self.amount,
                'partner': self.recipient,
                'project': self.project,
            },
            {
                'account': Account.objects.get(code='CASH'),
                'credit': self.amount,
            },
        ]

        entry = create_journal_entry(
            journal=Journal.objects.get(code='CASH'),
            date=self.date,
            lines=lines,
            reference=f"ADV-{self.advance_number}",
            user=user,
        )

        self.journal_entry = entry
        self.status = 'posted'
        self.save()
```

### 3.4 The Eight Posting Rules Implementation

| # | Document | Method | Debit Account | Credit Account | Partner | Project |
|---|----------|--------|---------------|----------------|---------|---------|
| 1 | CashAdvance | `post()` | Advances to PMs | Cash | recipient | project |
| 2 | Expense (with advance) | `post()` | Expense Account | Advances to PMs | advance.recipient | project |
| 3 | AdvanceReturn | `post()` | Cash | Advances to PMs | advance.recipient | advance.project |
| 4 | Invoice | `post()` | Accounts Receivable | Revenue | customer | project |
| 5 | Bill | `post()` | Expense Account | Accounts Payable | supplier | project (nullable) |
| 6 | Payment (inbound) | `post()` | Cash/Bank | Accounts Receivable | partner | — |
| 7 | Payment (outbound) | `post()` | Accounts Payable | Cash/Bank | partner | — |
| 8 | Expense (direct) | `post()` | Expense Account | Cash/Bank | vendor | project (nullable) |

### 3.5 Immutability Enforcement

```python
class JournalEntry(models.Model):
    def save(self, *args, **kwargs):
        if self.pk:
            old = JournalEntry.objects.get(pk=self.pk)
            if old.is_posted:
                # Only allow updating is_reversed and reversed_by
                allowed = {'is_reversed', 'reversed_by'}
                # Raise error if attempting to change other fields
        super().save(*args, **kwargs)
```

---

## 4. Permission Scoping Approach

### 4.1 Revised Roles (Updated)

**Three roles — no project manager app access:**
- **BusinessManager** (owner): Full access to everything
- **Accountant**: Full document access, manual journal entries, financial reports, no user management
- **DataEntry**: Create/edit drafts only, no posting, no reports, no settings

### 4.2 Permission Helper Functions

Location: `accounts/permissions.py`

```python
def is_business_manager(user: User) -> bool:
    return user.groups.filter(name='BusinessManager').exists()

def is_accountant(user: User) -> bool:
    return user.groups.filter(name='Accountant').exists()

def is_data_entry(user: User) -> bool:
    return user.groups.filter(name='DataEntry').exists()

def can_post_document(user: User) -> bool:
    return is_business_manager(user) or is_accountant(user)

def can_create_reversal(user: User) -> bool:
    return is_business_manager(user)

def can_create_manual_entry(user: User) -> bool:
    return is_business_manager(user) or is_accountant(user)

def can_manage_accounts(user: User) -> bool:
    return is_business_manager(user)

def can_manage_users(user: User) -> bool:
    return is_business_manager(user)

def can_view_reports(user: User) -> bool:
    return is_business_manager(user) or is_accountant(user)
```

### 4.3 Permission Matrix (Revised)

| Action | BusinessManager | Accountant | DataEntry |
|--------|-----------------|------------|-----------|
| View all projects | ✓ | ✓ | ✓ |
| View all ledgers | ✓ | ✓ | ✗ |
| Create/edit documents (draft) | ✓ | ✓ | ✓ |
| Post documents | ✓ | ✓ | ✗ |
| Create reversals | ✓ | ✗ | ✗ |
| Manual journal entries | ✓ | ✓ | ✗ |
| View financial reports | ✓ | ✓ | ✗ |
| Manage chart of accounts | ✓ | ✗ | ✗ |
| Manage journals | ✓ | ✗ | ✗ |
| Manage users | ✓ | ✗ | ✗ |
| Upload attachments | ✓ | ✓ | ✓ |

### 4.3 View Decorators

```python
# accounts/decorators.py
from functools import wraps
from django.http import HttpResponseForbidden

def admin_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not is_admin(request.user):
            return HttpResponseForbidden()
        return view_func(request, *args, **kwargs)
    return wrapper

def accounting_required(view_func):
    """Admin or Accounting"""
    ...

def project_access_required(view_func):
    """Check can_view_project for project in URL"""
    ...
```

---

## 5. Screen List with Navigation

### 5.1 Sidebar Navigation

```
┌─────────────────────────────────┐
│ [Logo] Construction ERP         │
├─────────────────────────────────┤
│ Dashboard                       │  ← /
│ Projects                        │  ← /projects/
│ ───────────────────────         │
│ Cash Advances                   │  ← /advances/
│ Expenses                        │  ← /expenses/
│ ───────────────────────         │
│ Invoices                        │  ← /invoices/
│ Bills                           │  ← /bills/
│ Payments                        │  ← /payments/
│ ───────────────────────         │
│ Receivables                     │  ← /receivables/       [BM, Acct]
│ Payables                        │  ← /payables/          [BM, Acct]
│ ───────────────────────         │
│ Documents                       │  ← /documents/
│ ───────────────────────         │
│ Reports ▼                       │                        [BM, Acct]
│   Income Statement              │  ← /reports/income-statement/
│   Balance Sheet                 │  ← /reports/balance-sheet/
│   Cash Flow                     │  ← /reports/cash-flow/
│   Project Profitability         │  ← /reports/project-profitability/
│ ───────────────────────         │
│ Accounting ▼                    │                        [BM, Acct]
│   Chart of Accounts             │  ← /accounting/accounts/  [BM only]
│   Journals                      │  ← /accounting/journals/  [BM only]
│   Journal Entries               │  ← /accounting/entries/
│   Ledger                        │  ← /accounting/ledger/
│   Trial Balance                 │  ← /accounting/trial-balance/
│ ───────────────────────         │
│ Settings ▼                      │                        [BM only]
│   Company                       │  ← /settings/company/
│   Users                         │  ← /settings/users/
└─────────────────────────────────┘
```

### 5.2 Screen Inventory

| Screen | URL | Roles | Description |
|--------|-----|-------|-------------|
| **Dashboard** | `/` | All | Summary cards, quick actions |
| **Project List** | `/projects/` | All | Dense table, filters by status |
| **Project Detail** | `/projects/<id>/` | All | Financial strip + tabbed data |
| **Advance List** | `/advances/` | All | Filter by project, status, recipient |
| **Advance Detail** | `/advances/<id>/` | All | Form + settlement box + tabs |
| **Advance Create** | `/advances/new/` | All | New advance form |
| **Expense List** | `/expenses/` | All | Filter by project, status, type |
| **Expense Detail** | `/expenses/<id>/` | All | Form + tabs |
| **Expense Create** | `/expenses/new/` | All | New expense form |
| **Invoice List** | `/invoices/` | All | Filter by customer, project, status |
| **Invoice Detail** | `/invoices/<id>/` | All | Form + payment status + tabs |
| **Invoice Create** | `/invoices/new/` | All | |
| **Bill List** | `/bills/` | All | Filter by supplier, project, status |
| **Bill Detail** | `/bills/<id>/` | All | Form + payment status + tabs |
| **Bill Create** | `/bills/new/` | All | |
| **Payment List** | `/payments/` | All | Filter by direction, partner |
| **Payment Detail** | `/payments/<id>/` | All | Form + allocations + tabs |
| **Payment Create** | `/payments/new/` | All | |
| **Receivables** | `/receivables/` | BM, Acct | Open AR by customer |
| **Payables** | `/payables/` | BM, Acct | Open AP by supplier |
| **Documents Index** | `/documents/` | All | All attachments across system |
| **Chart of Accounts** | `/accounting/accounts/` | BM | Account tree |
| **Journals** | `/accounting/journals/` | BM | Journal config |
| **Journal Entries** | `/accounting/entries/` | BM, Acct | All entries, filterable |
| **Journal Entry Create** | `/accounting/entries/new/` | BM, Acct | Manual journal entry |
| **Journal Entry Detail** | `/accounting/entries/<id>/` | BM, Acct | Read-only lines view |
| **Ledger** | `/accounting/ledger/` | BM, Acct | Account + date range filter |
| **Trial Balance** | `/accounting/trial-balance/` | BM, Acct | As-of-date report |
| **Income Statement** | `/reports/income-statement/` | BM, Acct | P&L report |
| **Balance Sheet** | `/reports/balance-sheet/` | BM, Acct | Assets = Liabilities + Equity |
| **Cash Flow** | `/reports/cash-flow/` | BM, Acct | Cash movements |
| **Project Profitability** | `/reports/project-profitability/` | BM, Acct | Revenue vs expenses per project |
| **Company Settings** | `/settings/company/` | BM | Company info |
| **User Management** | `/settings/users/` | BM | User CRUD |
| **Login** | `/login/` | Public | |
| **Logout** | `/logout/` | Authenticated | |

*BM = BusinessManager, Acct = Accountant, All = all logged-in users*

### 5.3 Document Detail Tabs

All document detail pages share this tab structure:
1. **Details** — The main form (editable if draft)
2. **Accounting Entry** — Read-only journal entry view (if posted)
3. **Attachments** — File upload/list
4. **History** — django-simple-history timeline

---

## 6. Design Notes and Decisions

### Note #1: Partner for Cash Advance Recipients

Cash advances are given to employees (e.g., site supervisors, foremen). The Partner model has `type='employee'` to track these individuals for subledger purposes. Journal lines reference Partner for Advances to PMs account tracking.

### Note #2: Expense Type Determination

Determined implicitly by field presence:
- `advance` is not null → Advance-linked expense (credits Advances to PMs)
- `advance` is null, `project` is not null → Direct project expense (credits Cash)
- `advance` is null, `project` is null → Company expense (credits Cash)

### Note #3: Payment Allocations

A single payment can be split across multiple invoices/bills (partial payments allowed). Validation ensures:
- Sum of allocations for a payment ≤ payment.amount
- Sum of allocations for an invoice/bill ≤ document.amount

### Note #4: PaperReceipt Register

Tracks physical receipts collected from field staff:
- Data entry receives physical receipt → creates PaperReceipt record
- Later, when entering Expense, links it to PaperReceipt (`matched=True`)
- Allows tracking: which receipts are still unmatched to expenses?

### Note #5: Manual Journal Entries

Both BusinessManager and Accountant can create manual journal entries. Control accounts (AR, AP, Advances) can only be used by BusinessManager in manual entries.

### Note #6: Reversal Mechanics

- Reversal creates a new JournalEntry with swapped debits/credits
- Original entry.is_reversed = True, linked to new entry
- Document status becomes 'cancelled'
- Only BusinessManager can create reversals

---

## 7. Default Chart of Accounts (Seed Data)

Proposed structure for `seed_demo`:

```
ASSETS (1xxx)
├── 1000 Cash
├── 1010 Bank - Operating
├── 1100 Accounts Receivable [control]
├── 1200 Advances to Project Managers [control]

LIABILITIES (2xxx)
├── 2000 Accounts Payable [control]

EQUITY (3xxx)
├── 3000 Owner's Equity
├── 3900 Retained Earnings

REVENUE (4xxx)
├── 4000 Project Revenue

EXPENSES (5xxx)
├── 5000 Materials
├── 5010 Labor - Subcontractor
├── 5020 Equipment Rental
├── 5030 Transportation
├── 5040 Permits & Fees
├── 5050 Site Expenses
├── 5090 Miscellaneous Project Expense
├── 5500 Office Supplies
├── 5510 Utilities
├── 5520 Administrative Expenses
```

Default Journals:
- `CASH` — Cash Journal
- `BANK` — Bank Journal
- `SALES` — Sales Journal (invoices)
- `PURCH` — Purchases Journal (bills)
- `GEN` — General Journal (manual entries)

---

## 8. Financial Reports

### 8.1 Report List

| Report | Description | Access |
|--------|-------------|--------|
| **Income Statement (قائمة الدخل)** | Revenue - Expenses = Net Income for period | BM, Acct |
| **Balance Sheet (الميزانية العمومية)** | Assets = Liabilities + Equity at date | BM, Acct |
| **Cash Flow (التدفقات النقدية)** | Cash movements by category | BM, Acct |
| **Trial Balance (ميزان المراجعة)** | All accounts with debit/credit totals | BM, Acct |
| **Project Profitability (ربحية المشاريع)** | Revenue vs Expenses per project | BM, Acct |
| **Receivables Aging (أعمار المديونيات)** | Open invoices by age bracket | BM, Acct |
| **Payables Aging (أعمار المستحقات)** | Open bills by age bracket | BM, Acct |
| **Advance Settlement (تسوية السلف)** | Advance status with expenses/returns | BM, Acct |

### 8.2 Report Parameters

All reports support:
- Date range (from/to)
- Project filter (optional)
- Export to PDF/Excel

---

*End of Architecture Review*
