# SPEC — qonto_banking, Phase 1 (MVP)

Goal: hourly sync of Qonto bank transactions into ERPNext `Bank Transaction` records.
No booking logic — reconciliation stays in ERPNext core. Out of scope for Phase 1:
attachments/receipts (Phase 2), webhooks (Phase 3), auto-matching rules & labels (Phase 4),
multiple Qonto organizations, OAuth.

## 1. App skeleton

Create with `bench new-app qonto_banking` (Title: "Qonto Banking", License: AGPL-3.0),
then `bench --site <site> install-app qonto_banking`.

Target layout inside the app package:

```
qonto_banking/
├─ hooks.py
├─ qonto_banking/doctype/
│  ├─ qonto_settings/          # Single DocType
│  └─ qonto_sync_log/
├─ api/client.py               # Qonto API wrapper
├─ sync.py                     # scheduler entry points + sync worker + mapping
└─ tests/
```

## 2. DocType: Qonto Settings (Single)

| Field | Type | Notes |
|---|---|---|
| `enabled` | Check | master switch for scheduled sync |
| `api_login` | Data | Qonto API login (slug) |
| `api_secret_key` | Password | read via `get_password()` |
| `sandbox_mode` | Check | use sandbox base URL |
| `staging_token` | Password | only relevant when sandbox_mode; sent as `X-Qonto-Staging-Token` |
| `sync_start_date` | Date | first-import lower bound (`settled_at_from`) |
| `company` | Link → Company | default company for created Bank Accounts |

Server-side buttons (whitelisted methods on the DocType, wired via form JS):

- **Test Connection** — calls `GET /v2/organization`; shows org name + account count,
  or a clear error (401 → "check login/secret").
- **Link Bank Accounts** — fetches `bank_accounts[]` from `/v2/organization`. Per Qonto
  account: find `Bank Account` by `integration_id`, else by matching `iban`
  (then set its `integration_id`), else create `Bank` ("Qonto") + `Bank Account`
  (name from Qonto `name`/`slug`, `iban`, `is_company_account=1`, `company` from settings).
  The GL `account` link is left for the user to set manually; the sync must skip accounts
  without it and say so in the sync log.

Permissions: System Manager + Accounts Manager only.

## 3. API client (`api/client.py`)

Small class `QontoClient` on top of `requests.Session`:

- Reads settings itself (or takes them injected — keep it testable).
- Base URL from `sandbox_mode`; headers: `Authorization: {login}:{secret}`,
  plus `X-Qonto-Staging-Token` in sandbox mode.
- `get_organization()` → dict.
- `iter_transactions(bank_account_id, settled_at_from, status="completed")` →
  generator over transactions; iterates `page` until `meta.next_page` is null;
  `per_page=100`; `sort_by=settled_at:asc`.
- Timeouts (connect 10 s / read 30 s). Retry with exponential backoff on 429 and 5xx
  (max 3 attempts). Raise a custom `QontoApiError` (carrying status code + body) on
  other 4xx — including 422 `search_limit_reached`.
- Never log the secret key.

## 4. Sync worker (`sync.py`)

Entry points:

- `scheduled_sync()` — registered in `hooks.py` under `scheduler_events["hourly"]`.
  Returns immediately unless `enabled`. For each `Bank Account` with a non-empty
  `integration_id` and a set GL `account`: `frappe.enqueue("...sync.sync_bank_account", queue="long", bank_account=name)`.
- `sync_all()` — same loop but synchronous, for manual runs via `bench execute`.
- `sync_bank_account(bank_account: str)` — the worker:

1. Compute `settled_at_from`: `last_integration_date - 3 days`, else
   `sync_start_date`, else fail with a clear message in the sync log.
2. Iterate transactions (completed only) via the client.
3. For each: skip if `frappe.db.exists("Bank Transaction", {"transaction_id": qonto_id})`;
   else build the doc (mapping below), `insert()`, `submit()`.
4. Per-transaction try/except: log the failure (`frappe.log_error` + counter),
   continue with the next transaction.
5. On success: set `last_integration_date` = today (db_set, no full save).
6. Always write a `Qonto Sync Log` entry (also on failure).

Concurrency guard: skip the run if another sync job for the same account is queued/running
(e.g. via `frappe.utils.background_jobs.is_job_enqueued` with a deterministic `job_id`).

## 5. Field mapping (Qonto transaction → Bank Transaction)

| Qonto | Bank Transaction | Rule |
|---|---|---|
| `id` | `transaction_id` | verbatim UUID |
| `settled_at` | `date` | date part, site timezone |
| `amount` if `side=credit` | `deposit` | absolute value |
| `amount` if `side=debit` | `withdrawal` | absolute value |
| `currency` | `currency` | |
| `label` (+ `note` appended if set) | `description` | `label` — Qonto's counterparty/subject line; append note separated by newline |
| `reference` | `reference_number` | may be null |
| `clean_counterparty_name`, fallback `label` | `bank_party_name` | |
| counterparty IBAN from `transfer`/`income` sub-object | `bank_party_iban` | only if present |
| `operation_type` | `transaction_type` | truncate to 50 chars |
| — | `bank_account` | the ERPNext Bank Account being synced |

## 6. DocType: Qonto Sync Log

Read-only list, newest first. Fields: `bank_account` (Link), `from_date` (Datetime),
`run_at` (Datetime), `status` (Select: Success/Partial/Failed), `new_transactions` (Int),
`skipped_existing` (Int), `errors` (Int), `details` (Small Text — first error messages).
Auto-delete entries older than 90 days (daily scheduler task).

## 7. hooks.py

```python
scheduler_events = {
    "hourly": ["qonto_banking.sync.scheduled_sync"],
    "daily": ["qonto_banking.sync.cleanup_sync_logs"],
}
```

## 8. Tests (tests/)

Mock `QontoClient` / HTTP layer. Required cases:

1. Mapping: credit → deposit, debit → withdrawal, note appended, missing reference ok,
   operation_type truncation, counterparty IBAN from sub-object.
2. Dedup: same transaction twice → one Bank Transaction.
3. Cursor: overlap window applied; first run uses `sync_start_date`; account without
   GL account is skipped.
4. Pagination: client follows `meta.next_page` until null.
5. Error isolation: one raising transaction → run continues, log says Partial.
6. Settings: sync disabled → scheduled_sync does nothing.

## 9. Acceptance criteria (Definition of Done)

- [ ] `bench --site <site> run-tests --app qonto_banking` passes.
- [ ] Fresh install: settings filled → Test Connection ok → Link Bank Accounts creates/links
      accounts → manual `sync_all` imports transactions visible in the Bank Transaction list
      as Unreconciled, correct amounts/sides/dates.
- [ ] Second run imports 0 new (dedup proven), sync log shows counts.
- [ ] Transactions reconcile normally in the Bank Reconciliation Tool.
- [ ] No secret ever appears in logs, error logs, or tracebacks.
- [ ] README.md (English): what it does, screenshots placeholder, install via
      `bench get-app`, setup steps, how reconciliation works, AGPL-3.0 license file.

## 10. Architecture

The app follows ERPNext's own Plaid integration
(`erpnext/erpnext_integrations/doctype/plaid_settings/plaid_settings.py`):
settings DocType → scheduler hook → `frappe.enqueue` per bank account → API fetch →
map → insert. Two deliberate departures: errors are isolated per transaction instead of
aborting the run, and the cursor only advances after a run without errors.

## 11. Qonto API reference

What the client depends on. Verified against the live API in July 2026.

- Base URL: `https://thirdparty.qonto.com`
- Sandbox: `https://thirdparty-sandbox.staging.qonto.co`, plus header
  `X-Qonto-Staging-Token: <token>`
- Auth header: `Authorization: {login}:{secret-key}` — the raw pair. **Not** HTTP Basic,
  not base64 encoded.
- `GET /v2/organization` → 200 with `organization.bank_accounts[]` (`id`, `iban`, `bic`,
  `currency`, `balance`, `name`, `status`, `main`); 401 on bad credentials. Doubles as
  the connection test.
- `GET /v2/transactions` requires `bank_account_id` (or `iban`). Filters: `status[]`
  (default completed), `settled_at_from`/`to`, `updated_at_from`/`to`, `side`
  (credit|debit), `operation_type[]`. Sort: `sort_by=settled_at:asc`. Pagination:
  `page`, `per_page` (max 100); `meta.next_page` is null on the last page.
  **Requesting a page beyond the last one answers 422, not an empty list.**
- Transaction fields used: `id`, `amount`, `side`, `currency`, `settled_at`, `label`,
  `clean_counterparty_name`, `note`, `reference`, `operation_type`, `status`, plus the
  type-specific sub-objects `transfer` / `income`, which may carry the counterparty IBAN.
- Rate limit: 1000 requests per 10 seconds per IP — far above what a sync needs, but 429
  is retried with backoff anyway.
- More than 10 000 results without narrow filters answers 422 `search_limit_reached`.
  The time-window cursor prevents it; the client reports it with a message pointing at
  the date range.
- Documentation is published as fetchable markdown: index at
  <https://docs.qonto.com/llms.txt>, append `.md` to any documentation page URL.
