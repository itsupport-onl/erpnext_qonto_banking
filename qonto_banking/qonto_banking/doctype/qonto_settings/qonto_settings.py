# Copyright (c) 2026, itsupport.online and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from qonto_banking.api.client import QontoClient

BANK_NAME = "Qonto"


class QontoSettings(Document):
	def validate(self):
		if self.enabled:
			self.refuse_to_arm_while_incomplete()

	def refuse_to_arm_while_incomplete(self):
		"""Switch the import back off instead of refusing the save.

		Blocking the save would deadlock a fresh setup: linking accounts needs a
		saved document, because the secret is read through get_password() from
		the database rather than from the form. So the settings always save, and
		only the automation refuses to come on.
		"""
		problem = self.why_not_ready()
		if not problem:
			return

		self.enabled = 0
		frappe.msgprint(problem, title=_("Import not switched on"), indicator="orange")

	@staticmethod
	def linked_accounts() -> list:
		"""Bank Accounts carrying a Qonto account id.

		Its own method so tests can replace it instead of deleting rows that
		belong to somebody's real setup.
		"""
		return frappe.get_all(
			"Bank Account",
			filters={"integration_id": ["is", "set"]},
			fields=["name", "account"],
		)

	def why_not_ready(self) -> str | None:
		"""Explain why importing cannot be armed yet, or None when it can.

		ERPNext does not allow a Bank Account to be a company account without a
		ledger account, so linked accounts start out incomplete. Importing into
		an incomplete account produces Bank Transactions nobody can reconcile.
		"""
		linked = self.linked_accounts()

		if not linked:
			return _(
				"No Qonto account is linked yet. Use <b>Link Bank Accounts</b>, give each"
				" account an entry from your chart of accounts, then switch the import on."
			)

		incomplete = [account.name for account in linked if not account.account]
		if not incomplete:
			return None

		links = "<br>".join(
			f"<a href='/app/bank-account/{frappe.utils.quoted(name)}'>{name}</a>" for name in incomplete
		)
		return (
			_(
				"These bank accounts still need an <b>Account</b> from your chart of"
				" accounts before transactions can be imported:"
			)
			+ f"<br><br>{links}<br><br>"
			+ _("Open each one, pick the account and tick <b>Is Company Account</b>.")
		)

	@frappe.whitelist()
	def test_connection(self) -> dict:
		"""Ask Qonto who we are, and check the accounts while we are at it."""
		organization = self._fetch_organization()
		accounts = organization.get("bank_accounts") or []
		return {
			"organization": organization.get("name") or organization.get("slug") or "?",
			"accounts": len(accounts),
			"warnings": self.currency_warnings(accounts),
		}

	@frappe.whitelist()
	def link_bank_accounts(self) -> dict:
		"""Match Qonto accounts to ERPNext Bank Accounts, creating what is missing."""
		organization = self._fetch_organization()
		accounts = organization.get("bank_accounts") or []

		result = {"created": [], "linked": [], "existing": []}
		for qonto_account in accounts:
			outcome, name = self._link_one(qonto_account)
			result[outcome].append({"name": name, "currency": qonto_account.get("currency")})

		result["warnings"] = self.currency_warnings(accounts)
		return result

	def _fetch_organization(self) -> dict:
		payload = QontoClient.from_settings(self).get_organization()
		return payload.get("organization") or {}

	def currency_warnings(self, qonto_accounts: list) -> list[str]:
		"""Report accounts whose ledger currency does not match Qonto's.

		ERPNext refuses a Bank Transaction whose currency differs from the bank
		account's, so a mismatch means every single transaction fails to import.
		Saying so here is cheaper than letting the sync discover it.
		"""
		warnings = []
		for qonto_account in qonto_accounts:
			qonto_currency = qonto_account.get("currency")
			if not qonto_currency:
				continue

			bank_account = frappe.db.get_value(
				"Bank Account",
				{"integration_id": qonto_account.get("id")},
				["name", "account"],
				as_dict=True,
			)
			if not bank_account or not bank_account.account:
				continue

			ledger_currency = frappe.db.get_value("Account", bank_account.account, "account_currency")
			if ledger_currency and ledger_currency != qonto_currency:
				warnings.append(
					_("{0}: Qonto keeps this account in {1}, but {2} is in {3}.").format(
						bank_account.name, qonto_currency, bank_account.account, ledger_currency
					)
				)
		return warnings

	def _link_one(self, qonto_account: dict) -> tuple[str, str]:
		integration_id = qonto_account.get("id")

		known = frappe.db.get_value("Bank Account", {"integration_id": integration_id})
		if known:
			return "existing", known

		iban = qonto_account.get("iban")
		if iban:
			by_iban = frappe.db.get_value("Bank Account", {"iban": iban})
			if by_iban:
				frappe.db.set_value("Bank Account", by_iban, "integration_id", integration_id)
				return "linked", by_iban

		return "created", self._create_bank_account(qonto_account)

	def _create_bank_account(self, qonto_account: dict) -> str:
		if not self.company:
			frappe.throw(_("Set a <b>Company</b> in Qonto Settings before linking accounts."))

		bank = self._ensure_bank()
		account_name = self._account_name(qonto_account, bank)

		doc = frappe.get_doc(
			{
				"doctype": "Bank Account",
				"account_name": account_name,
				"bank": bank,
				"company": self.company,
				"iban": qonto_account.get("iban"),
				"integration_id": qonto_account.get("id"),
				# Created incomplete on purpose: ERPNext rejects a company
				# account without a ledger account, and picking one is a chart
				# of accounts decision the user has to make.
				"is_company_account": 0,
			}
		)
		doc.insert()
		return doc.name

	@staticmethod
	def _ensure_bank() -> str:
		if not frappe.db.exists("Bank", BANK_NAME):
			frappe.get_doc({"doctype": "Bank", "bank_name": BANK_NAME}).insert()
		return BANK_NAME

	@staticmethod
	def _account_name(qonto_account: dict, bank: str) -> str:
		base = qonto_account.get("name") or qonto_account.get("slug") or qonto_account.get("id")
		if not frappe.db.exists("Bank Account", f"{base} - {bank}"):
			return base

		# Two Qonto accounts may carry the same name; keep both addressable.
		suffix = (qonto_account.get("id") or "")[-6:]
		return f"{base} {suffix}".strip()
