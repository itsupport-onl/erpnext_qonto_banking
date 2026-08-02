"""Shared test fixtures.

Not named test_*.py on purpose: the Frappe test runner must not collect this
module as a test file.
"""

import frappe

from qonto_banking.tests.compat import BaseTestCase


def transaction(**overrides) -> dict:
	"""A completed Qonto transaction, shaped like the real API response."""
	base = {
		"id": "qonto-txn-1",
		"amount": 123.45,
		"side": "debit",
		"currency": "EUR",
		"settled_at": "2026-03-15T12:00:00.000Z",
		"label": "ACME GmbH",
		"clean_counterparty_name": "ACME GmbH",
		"reference": "INV-2026-0042",
		"operation_type": "transfer",
		"status": "completed",
	}
	base.update(overrides)
	return base


class FakeClient:
	"""Stands in for QontoClient and records how it was called."""

	def __init__(self, *transactions, organization=None):
		self.transactions = list(transactions)
		self.organization = organization or {"organization": {"name": "ACME", "bank_accounts": []}}
		self.calls = []

	def iter_transactions(self, bank_account_id, settled_at_from=None, status="completed"):
		self.calls.append({"bank_account_id": bank_account_id, "settled_at_from": settled_at_from})
		yield from self.transactions

	def get_organization(self):
		self.calls.append({"organization": True})
		return self.organization


def _test_company() -> str:
	"""The company these tests hang their accounts off.

	Any company will do -- the tests never assert on its name -- but one has to
	exist, and that is the bootstrap's job rather than something to paper over
	here. Saying so out loud beats the AttributeError further down that this
	used to produce.
	"""
	company = frappe.db.get_value("Company", {}, "name")
	if not company:
		raise RuntimeError(
			"No Company on the test site. The before_tests hook"
			" (qonto_banking.tests.bootstrap) should have created one."
		)
	return company


def _bank_parent_account(company: str) -> str:
	"""A group account to hang our own bank ledger under.

	Asks for the *group* rather than an existing bank ledger on purpose. Every
	chart of accounts creates the "Bank Accounts" group, but a ready-made ledger
	underneath it only appears when the setup wizard is given a `bank_account`
	argument -- which is exactly the incidental detail this fixture used to
	depend on, and exactly what stopped being there on v16.
	"""
	group = frappe.db.get_value(
		"Account", {"company": company, "account_type": "Bank", "is_group": 1}, "name"
	)
	if group:
		return group

	# A non-standard chart may not type its bank group; any asset group will do.
	return frappe.db.get_value("Account", {"company": company, "is_group": 1, "root_type": "Asset"}, "name")


class QontoTestCase(BaseTestCase):
	"""Fixtures for tests that need a company bank account linked to Qonto."""

	def setUp(self):
		self.company = _test_company()

		# The v15 base class rolls back per class rather than per test, so records
		# survive between the tests of one class. Giving everything a unique name
		# does not depend on which base class BaseTestCase resolved to, which is
		# what keeps these fixtures working on v15 and v16 alike.
		self.prefix = frappe.generate_hash(length=8)

		# ERPNext allows a ledger account to back only one Bank Account, so each
		# test needs its own.
		self.gl_account = (
			frappe.get_doc(
				{
					"doctype": "Account",
					"account_name": f"Qonto Test {self.prefix}",
					"parent_account": _bank_parent_account(self.company),
					"company": self.company,
					"account_type": "Bank",
					"is_group": 0,
					"account_currency": "EUR",
				}
			)
			.insert()
			.name
		)

		if not frappe.db.exists("Bank", "Qonto Test Bank"):
			frappe.get_doc({"doctype": "Bank", "bank_name": "Qonto Test Bank"}).insert()

		# Written straight to the Singles table: saving the document runs the
		# guard that refuses to enable importing while accounts are incomplete,
		# which is exercised in its own tests.
		frappe.db.set_single_value("Qonto Settings", "enabled", 1)
		frappe.db.set_single_value("Qonto Settings", "sync_start_date", "2026-01-01")
		frappe.db.set_single_value("Qonto Settings", "company", self.company)

	def txn(self, suffix: str = "1", **overrides) -> dict:
		overrides.setdefault("id", f"{self.prefix}-{suffix}")
		return transaction(**overrides)

	def make_bank_account(self, suffix: str = "1", with_gl_account=True, last_date=None):
		"""Create a Bank Account linked to a Qonto account.

		with_gl_account=False models the state right after linking: ERPNext
		refuses a company account without a ledger account, so such a record can
		only exist with is_company_account unset.
		"""
		integration_id = f"{self.prefix}-{suffix}"
		doc = frappe.get_doc(
			{
				"doctype": "Bank Account",
				"account_name": f"Qonto {integration_id}",
				"bank": "Qonto Test Bank",
				"is_company_account": 1 if with_gl_account else 0,
				"company": self.company,
				"integration_id": integration_id,
			}
		)
		if with_gl_account:
			doc.account = self.gl_account
		if last_date:
			doc.last_integration_date = last_date

		doc.insert()
		return doc
