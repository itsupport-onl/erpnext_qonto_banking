# Contributing

Thanks for considering a contribution. This app syncs Qonto bank transactions into
ERPNext; scope, architecture and the Qonto API facts the client relies on are documented
in [SPEC.md](SPEC.md) — please read it before opening a PR that changes behaviour.

## Ground rules

- **Never commit credentials.** See [SECURITY.md](SECURITY.md). Use fake values in tests.
- The app **never books anything** — it only creates `Bank Transaction` records.
  Reconciliation stays in ERPNext core. Changing this needs a discussion first.
- Deviating from SPEC.md is fine when it is wrong — but say so in the issue/PR
  and update SPEC.md in the same change.

## Development setup

You need a working frappe-bench with ERPNext (v15) and a dev site:

```bash
bench get-app qonto_banking https://github.com/itsupport-onl/erpnext_qonto_banking.git
bench --site dev.localhost install-app qonto_banking
bench --site dev.localhost set-config developer_mode 1
bench --site dev.localhost migrate
```

`developer_mode` must be on, otherwise DocType changes are not exported to JSON files.

Install the git hooks once:

```bash
pip install pre-commit
pre-commit install
```

## Code style

- Python ≥ 3.10, Frappe/ERPNext v15 compatible (keep v16 in mind — no v15-only APIs).
- Formatting and linting: `ruff` via pre-commit (tabs, double quotes, line length 110).
  Run `pre-commit run --all-files` before pushing.
- No new third-party runtime dependencies beyond what Frappe ships.
- Code, docstrings, comments and commit messages in **English**.
- License headers are not required; the repository is AGPL-3.0 as a whole.

## Tests

```bash
bench --site dev.localhost run-tests --app qonto_banking
```

- Use `frappe.tests.utils.FrappeTestCase`.
- Mock the Qonto API with `unittest.mock` — **never** call the real API in tests.
- A change to sync logic needs coverage for: field mapping, deduplication,
  cursor/overlap window, pagination, and error isolation (one bad transaction must not
  abort the run). See SPEC.md section 8.

## Commits and pull requests

- One logical change per commit; imperative subject line
  (e.g. `Add pagination handling to QontoClient`).
- Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`, `chore:`) are welcome but
  not enforced.
- Open a PR against `main`, describe the *why*, and link the issue.
- CI (tests + linters) must be green. Add or update tests for behaviour changes and
  keep [CHANGELOG.md](CHANGELOG.md) under `## [Unreleased]` up to date.

## Reporting bugs

Use the issue templates. Include Frappe/ERPNext versions and the relevant part of the
`Qonto Sync Log` or Error Log — **with credentials and account identifiers redacted**.

## License

By contributing you agree that your contribution is licensed under
[AGPL-3.0](license.txt).
