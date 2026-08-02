# Qonto Banking for ERPNext

[![CI](https://github.com/itsupport-onl/erpnext_qonto_banking/actions/workflows/ci.yml/badge.svg)](https://github.com/itsupport-onl/erpnext_qonto_banking/actions/workflows/ci.yml)
[![License: AGPL v3](https://img.shields.io/badge/license-AGPL--3.0-blue.svg)](license.txt)
[![ERPNext v15 and v16](https://img.shields.io/badge/ERPNext-v15%20%7C%20v16-0089ff.svg)](https://erpnext.com)
[![Commercial support](https://img.shields.io/badge/commercial%20support-itsupport.online-1f883d.svg)](https://itsupport.online/)

Your [Qonto](https://qonto.com) transactions land in ERPNext by themselves, ready for
reconciliation — no CSV exports, no MT940 files, no manual upload every morning.

Built and maintained by **[itsupport.online](https://itsupport.online/)** — ERPNext,
network and IT security specialists from Berlin. Free to use forever;
[commercial support](#commercial-support) is there when you want someone else to run it.

> **Status: pre-1.0.** The app imports real transactions from the production Qonto API
> and its behaviour is covered by tests. It has not been through a month-end close, and
> no version has been tagged. Please read
> [Warranty and liability](#warranty-and-liability) before relying on it.

## What changes for you

Today someone downloads a statement from Qonto and imports it into ERPNext, on a rhythm
that depends on whoever remembers. With this app, completed Qonto transactions appear as
`Bank Transaction` records within the hour, every hour, and your team opens the **Bank
Reconciliation Tool** to a list that is already current.

Everything after that is unchanged. The app hands you the bank side of the reconciliation
and stops there.

## What it will never do

This is the important half, because it is what you are being asked to trust.

- **It never books anything.** No Journal Entries, no Payment Entries, no automatic
  matching, no guessing at accounts. Every posting decision stays with your team.
- **It cannot move money.** The Qonto API key is used for reading only. The app has no
  code that could initiate a transfer, and Qonto issues read-scoped keys for this.
- **It sends nothing anywhere.** Transactions go from Qonto into your own ERPNext. No
  third-party service, no analytics, no telemetry.
- **It does not delete or change what is already there.** It only inserts transactions
  it has not seen before.

## What you decide before it runs

Four decisions, none of which the software can make for you.

| Decision | Why it matters |
|---|---|
| **Which ledger account** each Qonto account posts to | This is the account your bank balance reconciles against. One ledger account per bank account — ERPNext does not allow sharing |
| **Which currency** that ledger account is kept in | It must match the Qonto account. ERPNext refuses to book a EUR transaction into an account kept in another currency, and the import will fail loudly rather than convert anything |
| **From which date** to import | The first import starts here. Choose the beginning of the period you still need to reconcile, not the account opening date |
| **Who may see the settings** | The settings page is restricted to *System Manager* and *Accounts Manager*. It holds the API credentials |

Until the first two are done, the automatic import refuses to switch on and tells you
which accounts are still incomplete. That is deliberate: a half-configured import that
silently produces nothing is worse than one that says why.

## Everyday operation

Once running, there is nothing to do. What to look at when you want to check:

- **Qonto Sync Log** — one entry per run and account, newest first, with counts of new,
  skipped and failed transactions. Entries older than 90 days are removed automatically.
  A run is `Success`, `Partial` (some transactions failed) or `Failed`.
- **Import transactions automatically** — the switch in Qonto Settings. Turning it off
  pauses everything without touching credentials or configuration, for instance while
  closing a period. Manual runs remain possible while it is off.

Skipped transactions are normal: every run re-reads the last three days, so late-settling
transactions are not missed. Anything already imported is recognised by its Qonto
transaction id and ignored, so nothing is ever duplicated.

## Where each field comes from

Useful when a description reads oddly or a reference is missing.

| In ERPNext | From Qonto |
|---|---|
| Date | `settled_at`, converted from UTC to your site's timezone before the day is taken |
| Deposit / Withdrawal | `amount`, placed on the side given by `side` (credit or debit) |
| Description | `label`, with the Qonto `note` appended on a second line when present |
| Reference Number | `reference` — often empty; Qonto does not require it |
| Party Name | `clean_counterparty_name`, falling back to `label` |
| Party IBAN | Only present for transfers and direct debits, never for card payments |
| Transaction Type | `operation_type` (`card`, `transfer`, `direct_debit`, `qonto_fee`, …) |

Only transactions Qonto reports as **completed** are imported. Pending authorisations are
ignored until they settle.

## Reconciliation

Imported transactions appear in the **Bank Reconciliation Tool** like any other bank feed:
match them against Payment Entries, Sales or Purchase Invoices, or create the
counter-booking from there. This app intentionally stays out of that step.

## When something looks wrong

Start at the **Qonto Sync Log** list.

| What you see | What it means |
|---|---|
| The import cannot be switched on | A linked account has no ledger account yet, or nothing is linked at all. The message names the accounts |
| `Failed`, one message about currencies | The ledger account is kept in a different currency than the Qonto account. Assign a matching one — *Test Connection* lists every mismatch |
| `Partial` | Some transactions could not be imported; the details name them, the full trace is in **Error Log**. The cursor stays put, so the next run retries them |
| `Failed`, credentials rejected | Wrong or revoked API key. Qonto answers 401 |
| No log entries at all | The scheduler is not running (your administrator: `bench doctor`), or no account carries a Qonto id |
| Everything skipped, nothing new | Normal. The three-day overlap re-read transactions that were already there |

Credentials never appear in any log. If you attach one to a support request, still check
it for IBANs, counterparty names and amounts first.

## Data protection and credentials

- **What is fetched:** the transactions of the bank accounts you linked, including
  counterparty names and IBANs. That is personal data under the GDPR, and it stays in
  your ERPNext — the app has no other destination.
- **Where the API key lives:** in an encrypted Password field on your site. It is not
  shown again after saving, does not appear in logs, error reports or exports, and is
  never written to this repository. See [SECURITY.md](SECURITY.md).
- **Revoking access:** delete the key in the Qonto app. The next run fails with a clear
  message; nothing already imported is affected.

## Setup

For whoever administers your ERPNext.

**Requirements:** Frappe Framework and ERPNext **v15 or v16** — both are exercised by CI
on every change — plus a Qonto Business account with an API key. Python comes with your
Frappe installation and is not a separate decision (v15 runs on 3.10–3.14, v16 requires
3.14). No third-party Python dependencies beyond what Frappe ships.

```bash
bench get-app https://github.com/itsupport-onl/erpnext_qonto_banking.git
bench --site <your-site> install-app qonto_banking
bench --site <your-site> migrate
```

Then open **Qonto Settings** — search bar (`Ctrl + G`) or `/app/qonto-settings`:

1. **Enter the API login and secret key** from the Qonto app
   (*Settings → Integrations and Partnerships → API key*).
2. Set **Company for new bank accounts**. It is read only while linking, when a Qonto
   account has no bank account in ERPNext yet.
3. Set **Import transactions from**.
4. Optional: tick **Use Qonto's test environment** and add the sandbox token to rehearse
   the whole setup against Qonto's sandbox.
5. **Test Connection** — reports the organization, how many accounts Qonto knows about,
   and any account whose ledger currency does not match. The button saves the form for
   you if needed.
6. **Link Bank Accounts** — matches Qonto accounts to ERPNext `Bank Account` records by
   integration id, then by IBAN, and creates what is missing. The summary lists every
   account with its currency.
7. Open each new **Bank Account**, pick an **Account** from the chart of accounts *in
   that currency*, and tick **Is Company Account**. ERPNext refuses a company bank
   account without a ledger account, which is why new ones start incomplete.
8. Tick **Import transactions automatically**.

Before handing over to the scheduler, run it once by hand and compare the result against
a real statement:

```bash
bench --site <your-site> execute qonto_banking.sync.sync_all
```

A manual run works while the automatic import is still off. Start with a narrow **Import
transactions from** window so the result can be checked line by line, then widen it —
re-running never duplicates anything.

## How the import works

| Step | Behaviour |
|---|---|
| Trigger | Hourly, one background job per bank account. A job still running is not started twice |
| Cursor | `Bank Account.last_integration_date` minus a 3-day overlap; the first run uses **Import transactions from** |
| Filter | Qonto `status=completed` only, sorted `settled_at:asc`, 100 per page |
| Dedup | Skip if a `Bank Transaction` with the same `transaction_id` exists — the overlap costs nothing |
| Errors | Per-transaction isolation: one bad record is logged and skipped, the rest import, the run ends `Partial` |
| Cursor advance | Only after a clean run, so a failed transaction cannot slide out of the window unnoticed |
| Result | `Bank Transaction` inserted and submitted, status `Unreconciled` |

The full algorithm and the DocType definitions are in [SPEC.md](SPEC.md).

## Screenshots

_To be added (`docs/screenshots/`)._

## Development

```bash
bench --site dev.localhost install-app qonto_banking
bench --site dev.localhost set-config developer_mode 1   # required for DocType JSON export
bench --site dev.localhost migrate
bench --site dev.localhost run-tests --app qonto_banking
```

Install the pre-commit hooks before your first commit:

```bash
pip install pre-commit && pre-commit install
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for conventions and the test strategy. Tests always
mock the Qonto API — they never touch the real service.

## Roadmap

| Phase | Scope |
|---|---|
| 1 (MVP) | Scheduled transaction sync into `Bank Transaction` — **done, pre-1.0** |
| 2 | Attachments and receipts from Qonto |
| 3 | Webhooks instead of polling |
| 4 | Auto-matching rules and Qonto labels |

Out of scope for now: multiple Qonto organizations, OAuth.

## Commercial support

This app is free software and stays that way — install it, run it, fork it, no strings
attached. Bug reports and pull requests are handled here in the repository, free of
charge (see [CONTRIBUTING.md](CONTRIBUTING.md)).

If you would rather not run it yourself, the people who build it can do it for you.
**[itsupport.online](https://itsupport.online/)** is an IT service provider from Berlin
working on ERPNext, networks and IT security:

| Service | What that means |
|---|---|
| **Installation & onboarding** | Bench installation, Qonto API setup, mapping of bank and ledger accounts on your site |
| **Hosting & operations** | Managed ERPNext, updates, backups, monitoring, scheduler health |
| **Custom development** | Roadmap features pulled forward, extra fields, other banks, tailored matching logic |
| **Support & training** | Reconciliation questions, migration away from manual statement imports |

**Get in touch:** [itsupport.online](https://itsupport.online/) ·
<tickets@itsupport.onl> · +49 (0)30 2359 0378 1

## License

[AGPL-3.0](license.txt) — © Coozinha UG (haftungsbeschränkt), Berlin, trading as
[itsupport.online](https://itsupport.online/), and contributors.

Legal notice / Impressum: <https://itsupport.online/impressum/>

## Warranty and liability

This program is free software: you can redistribute it and/or modify it under the terms
of the GNU Affero General Public License as published by the Free Software Foundation,
either version 3 of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful, but **WITHOUT ANY
WARRANTY**; without even the implied warranty of **MERCHANTABILITY** or **FITNESS FOR A
PARTICULAR PURPOSE**. See the GNU Affero General Public License for more details —
sections 15 and 16 of [license.txt](license.txt) carry the full disclaimer of warranty
and limitation of liability.

You should have received a copy of the GNU Affero General Public License along with this
program. If not, see <https://www.gnu.org/licenses/>.

### What this means in practice

This app touches accounting data. It only creates `Bank Transaction` records — it never
books anything, never posts to a ledger, and has no write access to your bank account.
Even so:

- **Check what it imports.** Amounts, dates, debit/credit sides and duplicates are your
  responsibility to verify. Your bank statement is the authoritative record, not what
  this app wrote into ERPNext.
- **Reconciliation decisions stay with you** and your accountant. The app deliberately
  makes none of them.
- **This is not tax or accounting advice.** Whether a booking is correct under the rules
  of your jurisdiction is not something software can answer for you.
- **Rehearse against the Qonto sandbox first**, and against a copy of your site before
  you point it at production data.

Using it is your decision and your risk. If you want someone to carry part of that risk
contractually, that is what a support agreement is for — see
[Commercial support](#commercial-support).

## Trademarks

This project is not affiliated with, endorsed by, or sponsored by Qonto (Olinda SA) or
Frappe Technologies. "Qonto", "ERPNext" and "Frappe" are trademarks of their respective
owners and are used here only to describe what the software interoperates with.
