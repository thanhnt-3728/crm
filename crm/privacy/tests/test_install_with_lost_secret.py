# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""`setup()` runs on install, on the patch and on "Restore defaults": a site restored with another `encryption_key`
(secret lost while entries exist) must not fail there, and must not make a new secret that would orphan every block."""

import frappe
from frappe.tests import IntegrationTestCase

from crm.fcrm.doctype.crm_privacy_settings.crm_privacy_settings import _stored_secret
from crm.privacy.install import setup
from crm.privacy.tests.make_test_user import block, forget_dnc_secret


class TestSetupWhenTheSecretWasLost(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		setup()
		block(("email", "marisol.vega@example.net"))
		forget_dnc_secret()
		self.addCleanup(frappe.db.rollback)

	def test_setup_does_not_raise(self):
		setup()

	def test_setup_does_not_make_a_new_secret(self):
		setup()
		self.assertIsNone(_stored_secret())

	def test_setup_still_creates_the_role_and_the_template(self):
		frappe.db.delete("Role", {"name": "Compliance"})
		setup()
		self.assertTrue(frappe.db.exists("Role", "Compliance"))

	def test_setup_creates_the_secret_on_a_site_with_no_entries(self):
		frappe.db.delete("CRM Do Not Contact")
		setup()
		self.assertTrue(_stored_secret())
