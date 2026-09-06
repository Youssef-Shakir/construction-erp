# Project A — Construction Accounting & Project Tracking ERP

Lightweight internal accounting + project-tracking system for a construction company.
Small accounting team, several project managers, multiple concurrent projects.
Do NOT recreate Odoo. Keep V1 small, correct, and practical.

## Stack (fixed — do not propose alternatives)

- Python 3.12, Django 5.x, PostgreSQL 16
- Server-rendered Django templates + HTMX for dynamic rows/filters/modals
- Tailwind CSS (via django-tailwind or a standalone CLI build), no component libraries
- django-simple-history for audit trail
- pytest + pytest-django for tests
- Money: `DecimalField(max_digits=18, decimal_places=2)` everywhere. Never float.

## Architecture principles

1. **Ledger is separate from documents.** The `accounting` app knows nothing about construction.
   It only has Account, Journal, JournalEntry, JournalLine and enforces debits == credits.
2. **Documents drive accounting.** Business documents (CashAdvance, Expense, Invoice, Bill,
   Payment, AdvanceReturn) each own a one-to-one `journal_entry`. A `post()` method builds the
   lines from fixed rules inside one `transaction.atomic()` block.
3. **Posted entries are immutable.** Corrections are reversals, never edits.
4. **Balances are derived, never stored.** Outstanding advance, paid amount, remaining amount,
   AR/AP totals are all computed from JournalLine (or linked payments). No cached balance fields.
5. **Every document: draft -> posted -> (cancelled via reversal).** Drafts generate no entry.
6. **Store `amount`, `currency`, `amount_base` on every monetary row** even though V1 is single
   currency. No exchange-rate tables yet.
7. **Attachments** use a GenericForeignKey so any document can carry files. Files stored on disk
   under MEDIA_ROOT/<app>/<model>/<id>/. Keep original filename, uploader, timestamp.
8. **Project is nullable** on expenses and bills (company-level expenses). Required on advances,
   invoices, and PM-submitted expenses.

## Django apps

- `core`        — Company settings, Partner (customer/supplier with type flag), Attachment, base mixins
- `accounts`    — custom User, roles (Groups: Admin, Accounting, ProjectManager), permission helpers
- `projects`    — Project (code, name, customer, managers M2M, status, dates), project overview queries
- `accounting`  — Account, AccountType, Journal, JournalEntry, JournalLine, posting engine, ledger views
- `advances`    — CashAdvance (open/closed), AdvanceReturn, settlement calculations
- `expenses`    — Expense (project or company), PaperReceipt register
- `invoicing`   — Invoice (customer), Bill (supplier), derived payment status
- `payments`    — Payment (in/out), allocation to invoice/bill
- `dashboard`   — dashboard + receivables/payables summary views

## Journal-generation rules (the eight rules — implement exactly)

| Document                     | Debit                                  | Credit                          |
|-----------------------------|----------------------------------------|---------------------------------|
| Cash advance to PM          | Advances to Project Managers (partner=PM, project) | Cash                    |
| PM expense against advance  | Expense account (project)              | Advances to PMs (partner=PM)    |
| Cash returned by PM         | Cash                                   | Advances to PMs (partner=PM)    |
| Customer invoice            | Accounts Receivable (partner, project) | Project Revenue (project)       |
| Supplier bill               | Expense account (project or none)      | Accounts Payable (partner, project) |
| Payment received            | Cash/Bank                              | Accounts Receivable (partner)   |
| Payment made                | Accounts Payable (partner)             | Cash/Bank                       |
| Direct company/project expense | Expense account (project or none)   | Cash/Bank                       |

Control accounts (AR, AP, Advances to PMs) are flagged `is_control=True` and cannot be selected
in manual journal entries by non-admins.

Advance settlement figures (all derived): original advance, total expenses posted, cash returned,
remaining = advance - expenses - returned, unaccounted = remaining once advance is closed.

## Roles

- **Admin**: everything, incl. users, chart of accounts, journals, manual/general journal entries, reversals.
- **Accounting**: create/edit/post all business documents, upload attachments, view all projects and ledgers.
  No access to users, accounts config, journals config, or reversals.
- **ProjectManager**: object-scoped to `Project.managers` containing self. View own projects, own advances,
  own outstanding balance. Can create expenses in `submitted` state (not post). Upload receipts.

Check permissions with helper functions in `accounts/permissions.py`, not scattered `if request.user.groups` checks.

## UI direction

Dense, professional, fast. Think "modern accounting software for people who work with numbers all day".
- 13–14px system font stack, 32px table rows, tabular right-aligned numerals
- One accent colour, 1px borders, NO shadows, NO gradients, NO card grids, NO animations
- Layout: fixed left sidebar (Dashboard, Projects, Cash Advances, Expenses, Invoices, Bills, Payments,
  Receivables/Payables, Documents, Accounting, Settings); content area = filter bar + dense table
- Document view: form on top; tabs below for Accounting Entry (read-only), Attachments, History
- Project page: compact financial strip (Revenue, Expenses, Margin, Receivables, Payables, Open Advances)
  above tabbed tables of everything tagged to that project
- Keyboard-friendly forms: sensible tab order, Enter to add line, Ctrl+S to save

## Conventions

- Fat models / service functions in `services.py` per app; thin views. Posting logic lives in
  `accounting/posting.py` and each document's `post()` delegates to it.
- Every model that matters gets `HistoricalRecords()` and `created_by`/`updated_by` via a base mixin.
- Tests are required for: posting engine (debits==credits, atomicity, immutability), each of the
  eight journal rules, settlement math, invoice paid/remaining/overdue derivation, and role scoping.
- Use `select_related`/`prefetch_related` in list views; ledgers are aggregated with `Sum()` in SQL.
- Seed data: `python manage.py seed_demo` creates a default construction chart of accounts, journals,
  three users (one per role), two projects, and a small set of documents.
- Commit after every completed step of the roadmap with a clear message.

## V1 roadmap (work in this order — do not skip ahead)

1. Project skeleton, settings, Postgres, pytest, Tailwind build, base templates + sidebar layout
2. `accounts`: custom User, three Groups, permission helpers, login page
3. `core`: Partner, Attachment, audit mixin. `projects`: Project + list/detail pages
4. `accounting`: Account, Journal, JournalEntry, JournalLine, posting engine + tests, default chart of accounts
5. `advances`: CashAdvance, AdvanceReturn, settlement box, PM scoping + tests
6. `expenses`: Expense (advance-linked, direct project, company), PaperReceipt register + tests
7. `invoicing`: Invoice, Bill, derived status + tests
8. `payments`: Payment in/out with allocation + tests; Receivables / Payables lists
9. Attachments UI on every document; History tab; Documents index page
10. Project overview page; Ledger, Journal, Journal Entry views; Trial balance
11. Dashboard; `seed_demo`; UI consistency pass

## Out of scope for V1

Payroll, HR, CRM, inventory, manufacturing, tax engine, workflow engine, multi-company,
plugin architecture, exchange rates, printed receipt generation, mobile app, REST API.
