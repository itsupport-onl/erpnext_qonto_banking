# Security Policy

## Reporting a vulnerability

Please **do not open a public issue** for security problems.

Report privately via GitHub's
[private vulnerability reporting](https://github.com/itsupport-onl/erpnext_qonto_banking/security/advisories/new)
or by email to <tickets@itsupport.onl>.

Include: affected version, a description of the issue, reproduction steps and — if
possible — a suggested fix. You will get an acknowledgement within 5 working days and
a status update at least every 14 days until the issue is resolved.

Please give us a reasonable window to ship a fix before disclosing publicly.

## Credentials must never enter this repository

This app handles Qonto API credentials. The following rules are non-negotiable:

- **No credentials in git.** No API login, secret key, staging token, session cookie,
  IBAN of a real account, site password or `site_config.json` — not in code, not in
  tests, not in fixtures, not in commit messages, not in issue or PR descriptions.
  This also applies to private repositories.
- Secrets live in the Frappe site only: `Qonto Settings.api_secret_key` and
  `staging_token` are **Password** fields (encrypted at rest) and are read exclusively
  via `doc.get_password(...)`.
- Secrets must never be logged. No secret in `frappe.log_error`, in exception messages,
  in tracebacks or in the `Qonto Sync Log`.
- Tests use mocked HTTP responses and obviously fake values (e.g. `login="test"`,
  `secret="dummy"`). They never contact the real Qonto API.
- `.gitignore` blocks the usual carriers (`.env`, `*.key`, `*.pem`, `site_config.json`,
  `credentials.*`, …) and the `detect-private-key` pre-commit hook runs on every commit —
  treat both as a safety net, not as permission to be careless.

### If a credential was committed anyway

1. **Revoke it immediately** in the Qonto app (*Settings → Integrations and
   Partnerships → API key*) and generate a new one. Assume it is compromised — deleting
   the commit does not un-leak it.
2. Report it to <tickets@itsupport.onl>.
3. Only then clean the history (`git filter-repo` / BFG) and force-push in coordination
   with the maintainers.

## Supported versions

The project is pre-release. Until 1.0, only the latest `main` receives fixes.
