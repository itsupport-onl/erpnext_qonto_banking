"""Import Qonto transactions into ERPNext Bank Transactions.

This module creates Bank Transaction records and nothing else. It posts no
journal entries, matches nothing and moves no money -- reconciliation stays in
ERPNext's Bank Reconciliation Tool where a human can see every decision.
"""

from datetime import datetime, timezone
from typing import Any

import frappe
from frappe import _
from frappe.utils import add_days, convert_utc_to_system_timezone, getdate, now_datetime, today
from frappe.utils.background_jobs import is_job_enqueued

from qonto_banking.api.client import QontoApiError, QontoClient

# Re-fetching a few days on every run costs nothing (the transaction id
# deduplicates) and covers transactions that settle late.
OVERLAP_DAYS = 3

LOG_RETENTION_DAYS = 90
MAX_LOGGED_ERRORS = 5
DETAILS_MAX_CHARS = 1000
TRANSACTION_TYPE_MAX_CHARS = 50

# Qonto puts the counterparty IBAN into a type-specific sub-object and does not
# use the same key everywhere, so look under all the names we know about.
IBAN_SUB_OBJECTS = ("transfer", "income")
IBAN_KEYS = ("counterparty_account_number", "counterparty_iban", "iban")


# --------------------------------------------------------------------------
# Entry points
# --------------------------------------------------------------------------


def scheduled_sync() -> None:
	"""Hourly scheduler hook. Does nothing unless the automation is switched on."""
	settings = frappe.get_single("Qonto Settings")
	if not settings.enabled:
		return

	for account in get_linked_bank_accounts():
		if not account.account:
			_log_missing_gl_account(account)
			continue

		job_id = _job_id(account.name)
		if is_job_enqueued(job_id):
			# A previous run is still going. Skipping is safe: the next tick
			# picks the account up again.
			continue

		frappe.enqueue(
			"qonto_banking.sync.sync_bank_account",
			queue="long",
			job_id=job_id,
			bank_account=account.name,
		)


def sync_all() -> list[dict]:
	"""Synchronous run for `bench execute`, used for manual testing.

	Deliberately ignores the Enabled switch: you must be able to try a fresh
	setup before handing it to the scheduler.
	"""
	results = []
	for account in get_linked_bank_accounts():
		if not account.account:
			results.append(_log_missing_gl_account(account))
			continue
		results.append(sync_bank_account(account.name))
	return results


def get_linked_bank_accounts() -> list[Any]:
	"""Bank Accounts that carry a Qonto account id."""
	return frappe.get_all(
		"Bank Account",
		filters={"integration_id": ["is", "set"]},
		fields=["name", "account", "integration_id", "last_integration_date"],
	)


def sync_bank_account(bank_account: str) -> dict:
	"""Import one bank account. Always writes a Qonto Sync Log entry."""
	account = frappe.get_doc("Bank Account", bank_account)
	settings = frappe.get_single("Qonto Settings")

	counts = {"new": 0, "skipped": 0, "errors": 0}
	errors: list[str] = []

	if not account.account:
		return _log_missing_gl_account(account)

	from_date = _from_date(account, settings)
	if not from_date:
		return _write_log(
			bank_account,
			None,
			"Failed",
			counts,
			_("No start date. Set 'Import transactions from' in Qonto Settings."),
		)

	ledger_currency = frappe.db.get_value("Account", account.account, "account_currency")

	try:
		client = QontoClient.from_settings(settings)
		for transaction in client.iter_transactions(account.integration_id, settled_at_from=from_date):
			mismatch = _currency_mismatch(transaction, ledger_currency, account)
			if mismatch:
				# Every transaction would fail the same way. One clear line in
				# the log beats a few hundred identical ERPNext errors.
				counts["errors"] += 1
				frappe.log_error(title=f"Qonto: currency mismatch on {bank_account}", message=mismatch)
				return _write_log(bank_account, from_date, "Failed", counts, mismatch)

			_import_one(transaction, account, counts, errors)
	except QontoApiError as exc:
		counts["errors"] += 1
		errors.append(str(exc))
		frappe.log_error(
			title=f"Qonto sync failed for {bank_account}",
			message=f"{exc}\n\nHTTP {exc.status_code}\n{exc.body or ''}",
		)
		return _write_log(bank_account, from_date, "Failed", counts, "\n".join(errors))

	if counts["errors"]:
		# Leave the cursor where it is. A transaction that failed must be
		# retried on the next run rather than silently drop out of the window.
		status = "Partial"
	else:
		status = "Success"
		frappe.db.set_value("Bank Account", bank_account, "last_integration_date", today())

	return _write_log(bank_account, from_date, status, counts, "\n".join(errors))


def cleanup_sync_logs() -> None:
	"""Daily scheduler hook: drop sync logs older than the retention window.

	No explicit commit: the scheduler commits after a successful job, and
	committing here would also make a caller's uncommitted work permanent.
	"""
	cutoff = add_days(today(), -LOG_RETENTION_DAYS)
	frappe.db.delete("Qonto Sync Log", {"run_at": ["<", cutoff]})


# --------------------------------------------------------------------------
# Import of a single transaction
# --------------------------------------------------------------------------


def _import_one(transaction: dict, account: Any, counts: dict, errors: list[str]) -> None:
	"""Import one transaction. A failure here must never abort the run."""
	transaction_id = transaction.get("id")

	frappe.db.savepoint("qonto_transaction")
	try:
		if frappe.db.exists("Bank Transaction", {"transaction_id": transaction_id}):
			counts["skipped"] += 1
			return

		doc = frappe.get_doc(map_transaction(transaction, account))
		doc.insert()
		doc.submit()
		counts["new"] += 1
	except Exception as exc:
		frappe.db.rollback(save_point="qonto_transaction")
		counts["errors"] += 1
		if len(errors) < MAX_LOGGED_ERRORS:
			errors.append(f"{transaction_id}: {exc}")
		frappe.log_error(
			title=f"Qonto: transaction {transaction_id} could not be imported",
			message=frappe.get_traceback(),
		)


def _currency_mismatch(transaction: dict, ledger_currency: str | None, account: Any) -> str | None:
	"""Explain a currency clash before it turns into a wall of errors."""
	currency = transaction.get("currency")
	if not currency or not ledger_currency or currency == ledger_currency:
		return None

	return _(
		"Qonto reports this account in {0}, but the account {1} is kept in {2}."
		" ERPNext cannot book a {0} transaction there. Assign an account in {0}"
		" to the bank account {3}, then run the import again."
	).format(currency, account.account, ledger_currency, account.name)


def map_transaction(transaction: dict, account: Any) -> dict:
	"""Map a Qonto transaction onto a Bank Transaction (SPEC.md section 5)."""
	amount = abs(float(transaction.get("amount") or 0))
	is_credit = transaction.get("side") == "credit"

	return {
		"doctype": "Bank Transaction",
		"bank_account": account.name,
		"transaction_id": transaction.get("id"),
		"date": settled_date(transaction.get("settled_at")),
		"deposit": amount if is_credit else 0,
		"withdrawal": 0 if is_credit else amount,
		"currency": transaction.get("currency"),
		"description": _description(transaction),
		"reference_number": transaction.get("reference"),
		"transaction_type": (transaction.get("operation_type") or "")[:TRANSACTION_TYPE_MAX_CHARS],
		"bank_party_name": transaction.get("clean_counterparty_name") or transaction.get("label"),
		"bank_party_iban": counterparty_iban(transaction),
	}


def settled_date(settled_at: str | None):
	"""Date part of a Qonto timestamp, in the site's timezone.

	Qonto reports UTC. Booking a late-evening UTC transaction on the wrong day
	would put it in the wrong period, so the conversion is not optional.
	"""
	if not settled_at:
		return None

	text = settled_at.strip()
	if text.endswith("Z"):
		text = f"{text[:-1]}+00:00"

	parsed = datetime.fromisoformat(text)
	if parsed.tzinfo:
		parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)

	return getdate(convert_utc_to_system_timezone(parsed))


def counterparty_iban(transaction: dict) -> str | None:
	for sub_object in IBAN_SUB_OBJECTS:
		details = transaction.get(sub_object) or {}
		if not isinstance(details, dict):
			continue
		for key in IBAN_KEYS:
			value = details.get(key)
			if value:
				return value
	return None


def _description(transaction: dict) -> str:
	parts = [transaction.get("label") or "", transaction.get("note") or ""]
	return "\n".join(part for part in parts if part)


# --------------------------------------------------------------------------
# Cursor and logging
# --------------------------------------------------------------------------


def _from_date(account: Any, settings: Any):
	if account.last_integration_date:
		return add_days(getdate(account.last_integration_date), -OVERLAP_DAYS)
	if settings.sync_start_date:
		return getdate(settings.sync_start_date)
	return None


def _job_id(bank_account: str) -> str:
	return f"qonto_sync::{bank_account}"


def _log_missing_gl_account(account: Any) -> dict:
	return _write_log(
		account.name,
		None,
		"Failed",
		{"new": 0, "skipped": 0, "errors": 0},
		_("No account set on the Bank Account, so transactions cannot be booked later."),
	)


def _write_log(
	bank_account: str,
	from_date: Any,
	status: str,
	counts: dict,
	details: str = "",
) -> dict:
	log = frappe.get_doc(
		{
			"doctype": "Qonto Sync Log",
			"bank_account": bank_account,
			"from_date": from_date,
			"run_at": now_datetime(),
			"status": status,
			"new_transactions": counts["new"],
			"skipped_existing": counts["skipped"],
			"errors": counts["errors"],
			"details": (details or "")[:DETAILS_MAX_CHARS] or None,
		}
	)
	log.insert(ignore_permissions=True)

	return {
		"bank_account": bank_account,
		"status": status,
		"log": log.name,
		**counts,
	}
