import frappe

from qonto_banking import hooks
from qonto_banking.tests.compat import BaseTestCase


class TestQontoBankingApp(BaseTestCase):
	"""Smoke tests for the app skeleton.

	They prove that the app installs, migrates and is wired up correctly. The
	behavioural tests for the sync itself land together with the implementation
	(see SPEC.md section 8) and always mock the Qonto API.
	"""

	def test_app_is_installed(self):
		self.assertIn("qonto_banking", frappe.get_installed_apps())

	def test_hooks_metadata(self):
		self.assertEqual(hooks.app_name, "qonto_banking")
		self.assertEqual(hooks.app_title, "Qonto Banking")
		self.assertIn("erpnext", hooks.required_apps)

	def test_module_is_registered(self):
		self.assertTrue(frappe.db.exists("Module Def", "Qonto Banking"))
		self.assertEqual(
			frappe.db.get_value("Module Def", "Qonto Banking", "app_name"),
			"qonto_banking",
		)

	def test_scheduler_events_are_importable(self):
		"""A scheduled method that cannot be imported breaks every scheduler tick.

		This guard is why the entries in hooks.py stay commented out until
		sync.py exists — and it keeps them honest once they are enabled.
		"""
		methods = []
		for value in getattr(hooks, "scheduler_events", {}).values():
			if isinstance(value, dict):
				# cron style: {"0 0 * * *": ["module.method", ...]}
				for entry in value.values():
					methods.extend(entry)
			else:
				methods.extend(value)

		for method in methods:
			with self.subTest(method=method):
				self.assertTrue(callable(frappe.get_attr(method)))
