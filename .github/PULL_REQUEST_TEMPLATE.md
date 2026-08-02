## What and why

<!-- What does this change, and which problem does it solve? Link the issue. -->

Closes #

## How to test

<!-- Steps to verify on a dev site, or which tests cover it. -->

## Checklist

- [ ] No credentials, real IBANs, tokens or customer data in code, tests, logs,
      screenshots or this description
- [ ] Tests added/updated; `bench --site <site> run-tests --app qonto_banking` passes
- [ ] Qonto API is mocked in tests — no real API calls
- [ ] `pre-commit run --all-files` passes
- [ ] SPEC.md updated if the behaviour deviates from the spec
- [ ] CHANGELOG.md updated under `## [Unreleased]`
