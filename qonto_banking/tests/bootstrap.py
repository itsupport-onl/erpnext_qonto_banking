"""Prepare a test site on ERPNext v15 and v16.

Our DocTypes link to Company and Bank Account, and building test records for
those pulls in ERPNext master data (chart of accounts, default company) that a
plain `install-app` does not create. v15 shipped
`erpnext.setup.utils.before_tests` for exactly this, and we pointed the
`before_tests` hook straight at it. v16 dropped that function, so the hook
raised ImportError and no test could run.

On v16 we drive ERPNext's setup wizard ourselves. Note *which* setup_complete:
`erpnext.setup.setup_wizard.setup_wizard.setup_complete` is marked "only for
programmatical use" and runs its three stages unconditionally. Frappe's
same-named `frappe.desk.page.setup_wizard.setup_wizard.setup_complete` -- the
one v15's before_tests called -- returns early whenever
`frappe.is_setup_complete()` is true, and that check reads
`Installed Application.is_setup_complete` through `all()`, which is true for an
empty result. Going through Frappe's entry point on v16 therefore succeeds
while doing nothing at all, which is how this first showed up: every test that
needed a Company failed, and nothing in the log said why.
"""

import frappe
from frappe.utils import now_datetime

# Mirrors the company ERPNext v15's before_tests created, so a test that passes
# on one version is looking at the same fixtures on the other. `bank_account` is
# the one addition: install_fixtures.create_bank_account returns early without
# it, and then the site has no non-group Bank account at all.
TEST_COMPANY = {
	"currency": "USD",
	"full_name": "Test User",
	"company_name": "Wind Power LLC",
	"company_abbr": "WP",
	"timezone": "America/New_York",
	"industry": "Manufacturing",
	"domain": "Manufacturing",
	"country": "United States",
	"language": "english",
	"company_tagline": "Testing",
	"email": "test@erpnext.com",
	"password": "test",
	"chart_of_accounts": "Standard",
	"bank_account": "Test Bank Account",
}


def before_tests() -> None:
	"""`before_tests` hook. Delegates to ERPNext where it still can."""
	try:
		from erpnext.setup.utils import before_tests as erpnext_before_tests
	except ImportError:
		# ERPNext v16 and later.
		_complete_setup()
	else:
		# ERPNext v15.
		erpnext_before_tests()


def _complete_setup() -> None:
	"""What ERPNext v15's before_tests did, built from what v16 still offers."""
	from erpnext.setup.setup_wizard.setup_wizard import setup_complete
	from erpnext.setup.utils import enable_all_roles_and_domains, set_defaults_for_tests

	frappe.clear_cache()

	if not frappe.db.a_row_exists("Company"):
		year = now_datetime().year
		# install_company reads these as attributes, so a plain dict will not do.
		setup_complete(
			frappe._dict({**TEST_COMPANY, "fy_start_date": f"{year}-01-01", "fy_end_date": f"{year}-12-31"})
		)

	# Item Prices left over from a previous run make unrelated ERPNext tests
	# flake; v15 cleared them here and the reason has not gone away.
	frappe.db.sql("delete from `tabItem Price`")

	enable_all_roles_and_domains()
	set_defaults_for_tests()

	frappe.db.commit()
