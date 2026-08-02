from unittest.mock import patch

import frappe

from qonto_banking.api.client import QontoClient
from qonto_banking.qonto_banking.doctype.qonto_settings.qonto_settings import QontoSettings
from qonto_banking.tests.fixtures import FakeClient, QontoTestCase

# Valid IBANs - ERPNext checks the checksum.
IBAN_A = "DE89370400440532013000"
IBAN_B = "FR1420041010050500013M02606"


def organization(*bank_accounts, name="ACME SAS") -> dict:
	return {"organization": {"name": name, "bank_accounts": list(bank_accounts)}}


class TestEnableGuard(QontoTestCase):
	"""Importing may only be armed once every linked account can be booked.

	The guard must never block the save. Linking reads the secret through
	get_password() and therefore needs a stored document, so a settings form
	that cannot be saved is a settings form that can never be completed.
	"""

	def settings(self):
		return frappe.get_single("Qonto Settings")

	def with_linked(self, *accounts):
		"""Pretend these are the linked accounts.

		Patching beats deleting: a test must never touch bank accounts that
		belong to a real setup on the same site.
		"""
		return patch.object(QontoSettings, "linked_accounts", staticmethod(lambda: list(accounts)))

	def test_credentials_save_even_though_importing_stays_off(self):
		doc = self.settings()
		doc.enabled = 1
		doc.api_login = f"login-{self.prefix}"

		with self.with_linked():
			doc.save()

		self.assertEqual(frappe.db.get_single_value("Qonto Settings", "api_login"), f"login-{self.prefix}")
		self.assertFalse(frappe.db.get_single_value("Qonto Settings", "enabled"))

	def test_reason_names_the_missing_link_step(self):
		with self.with_linked():
			self.assertIn("Link Bank Accounts", self.settings().why_not_ready())

	def test_stays_off_while_an_account_has_no_ledger_account(self):
		incomplete = frappe._dict(name=f"Qonto {self.prefix} - Qonto", account=None)

		doc = self.settings()
		doc.enabled = 1
		with self.with_linked(incomplete):
			doc.save()
			reason = doc.why_not_ready()

		self.assertFalse(frappe.db.get_single_value("Qonto Settings", "enabled"))
		self.assertIn(incomplete.name, reason)

	def test_allows_when_every_account_is_complete(self):
		complete = frappe._dict(name=f"Qonto {self.prefix} - Qonto", account=self.gl_account)

		doc = self.settings()
		doc.enabled = 1
		with self.with_linked(complete):
			doc.save()

		self.assertTrue(frappe.db.get_single_value("Qonto Settings", "enabled"))

	def test_switching_off_is_always_allowed(self):
		"""You must be able to stop the import even while things are broken."""
		incomplete = frappe._dict(name=f"Qonto {self.prefix} - Qonto", account=None)

		doc = self.settings()
		doc.enabled = 0
		with self.with_linked(incomplete):
			doc.save()

		self.assertFalse(frappe.db.get_single_value("Qonto Settings", "enabled"))


class TestTestConnection(QontoTestCase):
	def connect(self, *accounts) -> dict:
		client = FakeClient(organization=organization(*accounts))
		with patch.object(QontoClient, "from_settings", return_value=client):
			return frappe.get_single("Qonto Settings").test_connection()

	def test_reports_organization_and_account_count(self):
		result = self.connect({"id": "a"}, {"id": "b"})

		self.assertEqual(result["organization"], "ACME SAS")
		self.assertEqual(result["accounts"], 2)
		self.assertEqual(result["warnings"], [])

	def test_warns_when_the_ledger_currency_differs(self):
		"""The trap that makes every transaction fail to import."""
		account = self.make_bank_account(suffix="usd")  # ledger account is EUR

		result = self.connect({"id": account.integration_id, "currency": "USD"})

		self.assertEqual(len(result["warnings"]), 1)
		self.assertIn(account.name, result["warnings"][0])
		self.assertIn("USD", result["warnings"][0])
		self.assertIn("EUR", result["warnings"][0])

	def test_no_warning_when_the_currencies_match(self):
		account = self.make_bank_account(suffix="eur")
		result = self.connect({"id": account.integration_id, "currency": "EUR"})
		self.assertEqual(result["warnings"], [])

	def test_no_warning_while_the_account_has_no_ledger_account(self):
		"""Nothing to compare yet - the missing account guard covers that case."""
		account = self.make_bank_account(suffix="bare", with_gl_account=False)
		result = self.connect({"id": account.integration_id, "currency": "USD"})
		self.assertEqual(result["warnings"], [])


class TestLinkBankAccounts(QontoTestCase):
	def link(self, *qonto_accounts) -> dict:
		client = FakeClient(organization=organization(*qonto_accounts))
		with patch.object(QontoClient, "from_settings", return_value=client):
			return frappe.get_single("Qonto Settings").link_bank_accounts()

	def test_creates_a_missing_account_but_leaves_it_incomplete(self):
		integration_id = f"{self.prefix}-new"
		result = self.link(
			{"id": integration_id, "name": f"Main {self.prefix}", "iban": IBAN_A, "currency": "EUR"}
		)

		self.assertEqual(len(result["created"]), 1)
		self.assertEqual(result["created"][0]["currency"], "EUR", "the form shows it while linking")

		doc = frappe.get_doc("Bank Account", result["created"][0]["name"])
		self.assertEqual(doc.integration_id, integration_id)
		self.assertEqual(doc.iban, IBAN_A)
		self.assertEqual(doc.bank, "Qonto")
		self.assertFalse(doc.is_company_account, "ERPNext would require a ledger account")
		self.assertFalse(doc.account)

	def test_matches_an_existing_account_by_iban(self):
		existing = frappe.get_doc(
			{
				"doctype": "Bank Account",
				"account_name": f"House bank {self.prefix}",
				"bank": "Qonto Test Bank",
				"company": self.company,
				"iban": IBAN_B,
				"is_company_account": 0,
			}
		).insert()

		result = self.link({"id": f"{self.prefix}-iban", "name": "ignored", "iban": IBAN_B})

		self.assertEqual([entry["name"] for entry in result["linked"]], [existing.name])
		self.assertEqual(
			frappe.db.get_value("Bank Account", existing.name, "integration_id"),
			f"{self.prefix}-iban",
		)

	def test_recognises_an_already_linked_account(self):
		account = self.make_bank_account(suffix="known")
		result = self.link({"id": account.integration_id, "name": "whatever"})

		self.assertEqual([entry["name"] for entry in result["existing"]], [account.name])
		self.assertEqual(result["created"], [])

	def test_creates_the_qonto_bank_once(self):
		self.link({"id": f"{self.prefix}-b1", "name": f"One {self.prefix}"})
		self.link({"id": f"{self.prefix}-b2", "name": f"Two {self.prefix}"})

		self.assertEqual(frappe.db.count("Bank", {"name": "Qonto"}), 1)

	def test_two_accounts_with_the_same_name_stay_addressable(self):
		result = self.link(
			{"id": f"{self.prefix}-x1", "name": f"Same {self.prefix}"},
			{"id": f"{self.prefix}-x2", "name": f"Same {self.prefix}"},
		)

		names = [entry["name"] for entry in result["created"]]
		self.assertEqual(len(names), 2)
		self.assertEqual(len(set(names)), 2)

	def test_company_is_required(self):
		frappe.db.set_single_value("Qonto Settings", "company", None)
		with self.assertRaises(frappe.ValidationError) as ctx:
			self.link({"id": f"{self.prefix}-nc", "name": f"No company {self.prefix}"})

		self.assertIn("Company", str(ctx.exception))
