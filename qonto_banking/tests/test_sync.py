from datetime import date
from unittest.mock import patch

import frappe

from qonto_banking import sync
from qonto_banking.api.client import QontoApiError, QontoClient
from qonto_banking.tests.compat import BaseTestCase
from qonto_banking.tests.fixtures import FakeClient, QontoTestCase, transaction

ACCOUNT = frappe._dict(name="Qonto Test - QTB")


class TestMapping(BaseTestCase):
	"""SPEC.md section 5."""

	def test_credit_becomes_deposit(self):
		mapped = sync.map_transaction(transaction(side="credit", amount=50), ACCOUNT)
		self.assertEqual(mapped["deposit"], 50)
		self.assertEqual(mapped["withdrawal"], 0)

	def test_debit_becomes_withdrawal(self):
		mapped = sync.map_transaction(transaction(side="debit", amount=50), ACCOUNT)
		self.assertEqual(mapped["withdrawal"], 50)
		self.assertEqual(mapped["deposit"], 0)

	def test_amount_is_always_positive(self):
		"""Qonto reports the sign through side, but never trust a single source."""
		mapped = sync.map_transaction(transaction(side="debit", amount=-50), ACCOUNT)
		self.assertEqual(mapped["withdrawal"], 50)

	def test_note_is_appended_to_description(self):
		mapped = sync.map_transaction(transaction(note="Rechnung Februar"), ACCOUNT)
		self.assertEqual(mapped["description"], "ACME GmbH\nRechnung Februar")

	def test_description_without_note(self):
		self.assertEqual(sync.map_transaction(transaction(), ACCOUNT)["description"], "ACME GmbH")

	def test_missing_reference_is_allowed(self):
		self.assertIsNone(sync.map_transaction(transaction(reference=None), ACCOUNT)["reference_number"])

	def test_operation_type_is_truncated_to_fifty_chars(self):
		mapped = sync.map_transaction(transaction(operation_type="x" * 80), ACCOUNT)
		self.assertEqual(len(mapped["transaction_type"]), 50)

	def test_counterparty_name_falls_back_to_label(self):
		mapped = sync.map_transaction(transaction(clean_counterparty_name=None), ACCOUNT)
		self.assertEqual(mapped["bank_party_name"], "ACME GmbH")

	def test_iban_from_transfer_sub_object(self):
		mapped = sync.map_transaction(
			transaction(transfer={"counterparty_account_number": "DE02120300000000202051"}),
			ACCOUNT,
		)
		self.assertEqual(mapped["bank_party_iban"], "DE02120300000000202051")

	def test_iban_from_income_sub_object(self):
		mapped = sync.map_transaction(
			transaction(income={"counterparty_account_number": "FR1420041010050500013M02606"}),
			ACCOUNT,
		)
		self.assertEqual(mapped["bank_party_iban"], "FR1420041010050500013M02606")

	def test_iban_absent(self):
		self.assertIsNone(sync.map_transaction(transaction(), ACCOUNT)["bank_party_iban"])

	def test_transaction_id_is_taken_verbatim(self):
		mapped = sync.map_transaction(transaction(id="abc-123"), ACCOUNT)
		self.assertEqual(mapped["transaction_id"], "abc-123")


class TestSettledDate(BaseTestCase):
	def test_midday_utc_keeps_its_date_in_any_timezone(self):
		self.assertEqual(sync.settled_date("2026-03-15T12:00:00.000Z"), date(2026, 3, 15))

	def test_offset_notation_is_understood(self):
		self.assertEqual(sync.settled_date("2026-03-15T12:00:00+00:00"), date(2026, 3, 15))

	def test_missing_timestamp(self):
		self.assertIsNone(sync.settled_date(None))


class TestSyncBankAccount(QontoTestCase):
	def failing_on(self, suffix: str):
		"""Make exactly one transaction blow up during mapping.

		What is under test is the isolation - savepoint, counters, carrying on -
		not which ERPNext validation happens to reject a malformed record.
		"""
		original = sync.map_transaction

		def flaky(transaction, account):
			if str(transaction.get("id", "")).endswith(f"-{suffix}"):
				raise ValueError("unmappable transaction")
			return original(transaction, account)

		return patch.object(sync, "map_transaction", side_effect=flaky)

	def test_imports_and_submits(self):
		account = self.make_bank_account()
		with patch.object(QontoClient, "from_settings", return_value=FakeClient(self.txn())):
			result = sync.sync_bank_account(account.name)

		self.assertEqual(result["status"], "Success")
		self.assertEqual(result["new"], 1)

		name = frappe.db.get_value("Bank Transaction", {"transaction_id": f"{self.prefix}-1"})
		doc = frappe.get_doc("Bank Transaction", name)
		self.assertEqual(doc.docstatus, 1, "Bank Transactions must be submitted")
		self.assertEqual(doc.status, "Unreconciled")
		self.assertEqual(doc.withdrawal, 123.45)

	def test_same_transaction_twice_creates_one_record(self):
		"""SPEC.md section 8, case 2: the overlap window must not duplicate."""
		account = self.make_bank_account()
		with patch.object(QontoClient, "from_settings", return_value=FakeClient(self.txn())):
			sync.sync_bank_account(account.name)
		with patch.object(QontoClient, "from_settings", return_value=FakeClient(self.txn())):
			second = sync.sync_bank_account(account.name)

		self.assertEqual(second["new"], 0)
		self.assertEqual(second["skipped"], 1)
		self.assertEqual(
			frappe.db.count("Bank Transaction", {"transaction_id": f"{self.prefix}-1"}),
			1,
		)

	def test_one_bad_transaction_does_not_abort_the_run(self):
		"""SPEC.md section 8, case 5."""
		account = self.make_bank_account()
		broken = self.txn("broken")
		good = self.txn("good")

		with patch.object(QontoClient, "from_settings", return_value=FakeClient(broken, good)):
			with self.failing_on("broken"):
				result = sync.sync_bank_account(account.name)

		self.assertEqual(result["status"], "Partial")
		self.assertEqual(result["errors"], 1)
		self.assertEqual(result["new"], 1)
		self.assertTrue(frappe.db.exists("Bank Transaction", {"transaction_id": f"{self.prefix}-good"}))
		self.assertFalse(frappe.db.exists("Bank Transaction", {"transaction_id": f"{self.prefix}-broken"}))

	def test_cursor_uses_sync_start_date_on_first_run(self):
		account = self.make_bank_account()
		client = FakeClient()
		with patch.object(QontoClient, "from_settings", return_value=client):
			sync.sync_bank_account(account.name)

		self.assertEqual(client.calls[0]["settled_at_from"], date(2026, 1, 1))

	def test_cursor_applies_the_overlap_window(self):
		"""SPEC.md section 8, case 3: last_integration_date minus three days."""
		account = self.make_bank_account(last_date="2026-06-20")
		client = FakeClient()
		with patch.object(QontoClient, "from_settings", return_value=client):
			sync.sync_bank_account(account.name)

		self.assertEqual(client.calls[0]["settled_at_from"], date(2026, 6, 17))

	def test_cursor_advances_only_on_a_clean_run(self):
		account = self.make_bank_account(last_date="2026-06-20")
		with patch.object(
			QontoClient,
			"from_settings",
			return_value=FakeClient(self.txn("broken")),
		):
			with self.failing_on("broken"):
				sync.sync_bank_account(account.name)

		unchanged = frappe.db.get_value("Bank Account", account.name, "last_integration_date")
		self.assertEqual(str(unchanged), "2026-06-20")

	def test_account_without_gl_account_is_skipped_and_logged(self):
		account = self.make_bank_account(suffix="no-gl", with_gl_account=False)
		with patch.object(QontoClient, "from_settings", return_value=FakeClient(self.txn())):
			result = sync.sync_bank_account(account.name)

		self.assertEqual(result["status"], "Failed")
		self.assertEqual(result["new"], 0)
		details = frappe.db.get_value("Qonto Sync Log", result["log"], "details")
		self.assertIn("account", details.lower())

	def test_api_failure_is_logged_not_raised(self):
		account = self.make_bank_account()
		client = FakeClient()
		client.iter_transactions = lambda *args, **kwargs: (_ for _ in ()).throw(
			QontoApiError("Qonto rejected the credentials.", status_code=401, body="nope")
		)

		with patch.object(QontoClient, "from_settings", return_value=client):
			result = sync.sync_bank_account(account.name)

		self.assertEqual(result["status"], "Failed")
		self.assertEqual(result["errors"], 1)

	def test_currency_mismatch_fails_the_run_once(self):
		"""ERPNext rejects every transaction in the wrong currency, so say it once."""
		account = self.make_bank_account()  # ledger account is EUR
		client = FakeClient(self.txn("a", currency="USD"), self.txn("b", currency="USD"))

		with patch.object(QontoClient, "from_settings", return_value=client):
			result = sync.sync_bank_account(account.name)

		self.assertEqual(result["status"], "Failed")
		self.assertEqual(result["errors"], 1, "one message, not one per transaction")
		self.assertEqual(result["new"], 0)

		details = frappe.db.get_value("Qonto Sync Log", result["log"], "details")
		self.assertIn("USD", details)
		self.assertIn("EUR", details)

	def test_every_run_writes_a_log(self):
		account = self.make_bank_account()
		before = frappe.db.count("Qonto Sync Log")
		with patch.object(QontoClient, "from_settings", return_value=FakeClient()):
			sync.sync_bank_account(account.name)

		self.assertEqual(frappe.db.count("Qonto Sync Log"), before + 1)


class TestScheduledSync(QontoTestCase):
	def test_disabled_does_nothing(self):
		"""SPEC.md section 8, case 6."""
		self.make_bank_account()
		frappe.db.set_single_value("Qonto Settings", "enabled", 0)

		with patch("qonto_banking.sync.frappe.enqueue") as enqueue:
			sync.scheduled_sync()

		enqueue.assert_not_called()

	def test_enabled_enqueues_one_job_per_account(self):
		account = self.make_bank_account()
		with patch("qonto_banking.sync.frappe.enqueue") as enqueue:
			with patch("qonto_banking.sync.is_job_enqueued", return_value=False):
				sync.scheduled_sync()

		# Other tests of this class may have left bank accounts behind, so look
		# at the call for this account rather than at the total count.
		enqueued = [call.kwargs["bank_account"] for call in enqueue.call_args_list]
		self.assertEqual(enqueued.count(account.name), 1)

		ours = next(c for c in enqueue.call_args_list if c.kwargs["bank_account"] == account.name)
		self.assertEqual(ours.kwargs["queue"], "long")
		self.assertIn(account.name, ours.kwargs["job_id"])

	def test_running_job_is_not_enqueued_twice(self):
		self.make_bank_account()
		with patch("qonto_banking.sync.frappe.enqueue") as enqueue:
			with patch("qonto_banking.sync.is_job_enqueued", return_value=True):
				sync.scheduled_sync()

		enqueue.assert_not_called()


class TestCleanup(QontoTestCase):
	def test_old_logs_are_deleted(self):
		account = self.make_bank_account()
		with patch.object(QontoClient, "from_settings", return_value=FakeClient()):
			result = sync.sync_bank_account(account.name)

		frappe.db.set_value("Qonto Sync Log", result["log"], "run_at", "2020-01-01 00:00:00")
		sync.cleanup_sync_logs()

		self.assertFalse(frappe.db.exists("Qonto Sync Log", result["log"]))
