# Changelog

All notable changes to this project are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-09-04

### Added

- Support for ERPNext and Frappe **v16** alongside v15. The runtime code needed
  no change — every Frappe API and every Bank Transaction / Bank Account field
  it touches exists unchanged in v16 — so this is about proving it and removing
  the two places where the test harness was pinned to v15.
- CI runs the suite against `version-15` and `version-16`. Python and Node moved
  into the matrix: the versions do not overlap (v15 wants Python >=3.10,<3.15
  and Node >=18, v16 narrows it to Python >=3.14,<3.15 and Node >=24).
- `qonto_banking/tests/compat.py`: one base test class for both versions. v16
  replaced `frappe.tests.utils.FrappeTestCase` with
  `frappe.tests.IntegrationTestCase`; the old name still resolves on v16 but
  only through a shim that announces its removal in v17.
- `qonto_banking/tests/bootstrap.py`: test-site setup for both versions.

### Changed

- The `before_tests` hook now points at `qonto_banking.tests.bootstrap`. It used
  to point straight at `erpnext.setup.utils.before_tests`, which ERPNext v16
  removed — on v16 the hook raised ImportError and no test could run. This was
  the only hard incompatibility in the app.
- Test fixtures create the ledger account they need under the "Bank Accounts"
  group instead of discovering an existing bank ledger. That ledger was never
  part of the chart of accounts — it only appeared because the v15 setup wizard
  happened to leave one behind — so the fixtures were resting on an accident
  that v16 no longer produces.
- Repository renamed to `erpnext_qonto_banking`. The Frappe app and Python
  package stay `qonto_banking`; `bench` reads the name from `pyproject.toml` and
  renames the folder to match, so `bench get-app` is unaffected. GitHub redirects
  the old URLs, so existing clones keep working.

## [0.1.0] - 2026-07-30

First release. The MVP is complete: Qonto transactions are imported into ERPNext
`Bank Transaction` records on a schedule, deduplicated, and left for reconciliation
in ERPNext's own Bank Reconciliation Tool. The app books nothing.

### Added

- Frappe v15 app skeleton (`qonto_banking` package, `hooks.py`, `pyproject.toml`).
- Implementation spec (`SPEC.md`), including the Qonto API reference.
- Open-source scaffolding: AGPL-3.0 license, README, contributing guide,
  security policy, code of conduct, issue/PR templates, CI and pre-commit setup.
- Smoke tests (`qonto_banking/tests/test_app.py`): app installation, hooks
  metadata, module registration and resolvability of all scheduler events.
- Maintainer attribution, status badges and a commercial support section in the
  README; copyright holder and legal notice made explicit.
- Warranty and liability section in the README, based on the AGPL-3.0 notice.
- DocTypes `Qonto Settings` (Single) and `Qonto Sync Log` per SPEC.md sections 2
  and 6, with tests guarding their field, permission and read-only invariants.
- `before_tests` hook so the test runner can build ERPNext-dependent test records.
- Help section in Qonto Settings linking to the setup guide, the issue tracker
  and commercial support.
- Qonto API client (`api/client.py`) per SPEC.md section 3: raw `login:secret`
  auth, sandbox support, pagination via `meta.next_page`, retry with exponential
  backoff on 429 and 5xx, `QontoApiError` carrying status code and body.
- Sync worker (`sync.py`) per SPEC.md sections 4 to 6: scheduler and manual entry
  points, cursor with a three-day overlap, deduplication on `transaction_id`,
  per-transaction error isolation, sync log per run, log retention cleanup.
- Plainer field labels and help texts in Qonto Settings.
- Scheduler events: hourly sync and daily sync-log cleanup (SPEC.md section 7).
- Buttons **Test Connection** and **Link Bank Accounts** in Qonto Settings, plus a
  guard that refuses to enable importing while a linked account has no ledger
  account.
- Currency checks: linking shows each Qonto account's currency, Test Connection
  reports accounts whose ledger currency differs, and the sync fails a run with
  one clear message instead of one error per transaction.

### Notes

- Verified against the production Qonto API: transactions imported, a second run
  imported nothing new, and no credential appeared in any log.
- Not yet exercised through a month-end close. Treat 0.1.0 as ready to evaluate,
  not as ready to depend on.

[Unreleased]: https://github.com/itsupport-onl/erpnext_qonto_banking/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/itsupport-onl/erpnext_qonto_banking/releases/tag/v0.1.0
