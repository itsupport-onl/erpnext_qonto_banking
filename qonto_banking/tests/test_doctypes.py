import frappe

from qonto_banking.tests.compat import BaseTestCase

SETTINGS_FIELDS = {
	"enabled": "Check",
	"api_login": "Data",
	"api_secret_key": "Password",
	"sandbox_mode": "Check",
	"staging_token": "Password",
	"sync_start_date": "Date",
	"company": "Link",
}

SYNC_LOG_FIELDS = {
	"bank_account": "Link",
	"from_date": "Datetime",
	"run_at": "Datetime",
	"status": "Select",
	"new_transactions": "Int",
	"skipped_existing": "Int",
	"errors": "Int",
	"details": "Small Text",
}


class TestQontoSettings(BaseTestCase):
	"""Guards the Qonto Settings DocType against SPEC.md section 2."""

	def test_is_single(self):
		self.assertTrue(frappe.get_meta("Qonto Settings").issingle)

	def test_fields(self):
		meta = frappe.get_meta("Qonto Settings")
		for fieldname, fieldtype in SETTINGS_FIELDS.items():
			with self.subTest(field=fieldname):
				df = meta.get_field(fieldname)
				self.assertIsNotNone(df, f"field {fieldname} is missing")
				self.assertEqual(df.fieldtype, fieldtype)

	def test_secrets_use_password_fields(self):
		"""Credentials must be encrypted at rest, never stored in a Data field."""
		meta = frappe.get_meta("Qonto Settings")
		for fieldname in ("api_secret_key", "staging_token"):
			with self.subTest(field=fieldname):
				self.assertEqual(meta.get_field(fieldname).fieldtype, "Password")

	def test_company_links_to_company(self):
		self.assertEqual(frappe.get_meta("Qonto Settings").get_field("company").options, "Company")

	def test_restricted_to_two_roles(self):
		roles = {p.role for p in frappe.get_meta("Qonto Settings").permissions}
		self.assertEqual(roles, {"System Manager", "Accounts Manager"})


class TestQontoSyncLog(BaseTestCase):
	"""Guards the Qonto Sync Log DocType against SPEC.md section 6."""

	def test_fields(self):
		meta = frappe.get_meta("Qonto Sync Log")
		for fieldname, fieldtype in SYNC_LOG_FIELDS.items():
			with self.subTest(field=fieldname):
				df = meta.get_field(fieldname)
				self.assertIsNotNone(df, f"field {fieldname} is missing")
				self.assertEqual(df.fieldtype, fieldtype)

	def test_status_options(self):
		options = frappe.get_meta("Qonto Sync Log").get_field("status").options.split("\n")
		self.assertEqual(options, ["Success", "Partial", "Failed"])

	def test_bank_account_links_to_bank_account(self):
		field = frappe.get_meta("Qonto Sync Log").get_field("bank_account")
		self.assertEqual(field.options, "Bank Account")

	def test_newest_first(self):
		meta = frappe.get_meta("Qonto Sync Log")
		self.assertEqual(meta.sort_field, "run_at")
		self.assertEqual(meta.sort_order, "DESC")

	def test_fields_are_read_only(self):
		"""The log is written by the sync worker, not by hand."""
		meta = frappe.get_meta("Qonto Sync Log")
		for fieldname in SYNC_LOG_FIELDS:
			with self.subTest(field=fieldname):
				self.assertTrue(meta.get_field(fieldname).read_only, f"{fieldname} is editable")

	def test_doctype_is_read_only(self):
		self.assertTrue(frappe.get_meta("Qonto Sync Log").read_only)

	def test_no_role_may_write_or_create(self):
		for perm in frappe.get_meta("Qonto Sync Log").permissions:
			with self.subTest(role=perm.role):
				self.assertFalse(perm.write, f"{perm.role} must not write sync logs")
				self.assertFalse(perm.create, f"{perm.role} must not create sync logs")

	def test_only_system_manager_may_delete(self):
		"""Deleting a failed run would quietly destroy the audit trail."""
		for perm in frappe.get_meta("Qonto Sync Log").permissions:
			if perm.role != "System Manager":
				with self.subTest(role=perm.role):
					self.assertFalse(perm.delete, f"{perm.role} must not delete sync logs")

	def test_worker_can_still_insert(self):
		"""read_only guards the UI; the sync worker must remain able to write."""
		log = frappe.get_doc(
			{
				"doctype": "Qonto Sync Log",
				"run_at": frappe.utils.now_datetime(),
				"status": "Success",
				"new_transactions": 0,
			}
		)
		log.insert(ignore_permissions=True)
		self.assertTrue(frappe.db.exists("Qonto Sync Log", log.name))
