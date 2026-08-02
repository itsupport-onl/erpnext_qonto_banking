"""One test base class for Frappe v15 and v16.

v16 replaced `frappe.tests.utils.FrappeTestCase` with
`frappe.tests.IntegrationTestCase`. The old import still resolves on v16, but
only through a shim in `frappe/deprecation_dumpster.py` that announces its own
removal in v17 -- so importing it directly would leave a dated trap in the
suite. v15 has no `IntegrationTestCase` at all, hence the try/except rather
than a version number: we ask what the installation offers instead of guessing
from a version string.

Frappe's own note on the shim says IntegrationTestCase is "overwhelmingly
api-compatible", and everything this suite uses (setUp, subTest, assertRaises)
is plain unittest.
"""

try:
	# Frappe v16 and later.
	from frappe.tests import IntegrationTestCase as BaseTestCase
except ImportError:
	# Frappe v15.
	from frappe.tests.utils import FrappeTestCase as BaseTestCase

__all__ = ["BaseTestCase"]
