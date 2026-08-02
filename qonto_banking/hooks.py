app_name = "qonto_banking"
app_title = "Qonto Banking"
app_publisher = "itsupport.online"
app_description = "Sync Qonto Business bank transactions into ERPNext Bank Transactions"
app_email = "tickets@itsupport.onl"
app_license = "agpl-3.0"

required_apps = ["erpnext"]

# Testing
# -------
# Frappe runs before_tests hooks only for the app under test, so ERPNext's own
# hook does not fire for us. Without it the test runner cannot build test records
# for our DocTypes: they link to Company and Bank Account, and creating those
# pulls in ERPNext master data (warehouse types, default company) that a plain
# install-app does not create.
#
# This used to point at erpnext.setup.utils.before_tests directly. ERPNext v16
# removed that function, so the indirection is what keeps one code base running
# on both versions -- see qonto_banking/tests/bootstrap.py.
before_tests = "qonto_banking.tests.bootstrap.before_tests"

# Scheduled tasks
# ---------------
# scheduled_sync returns immediately unless "Import transactions automatically"
# is switched on in Qonto Settings, so installing the app does not start
# fetching anything by itself.
scheduler_events = {
	"hourly": ["qonto_banking.sync.scheduled_sync"],
	"daily": ["qonto_banking.sync.cleanup_sync_logs"],
}

# Includes in <head>
# ------------------
# app_include_css = "/assets/qonto_banking/css/qonto_banking.css"
# app_include_js = "/assets/qonto_banking/js/qonto_banking.js"

# Document Events
# ---------------
# doc_events = {}

# Fixtures
# --------
# fixtures = []
