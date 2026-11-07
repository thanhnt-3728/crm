# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Shared setup for the privacy settings endpoint tests."""

import frappe
from frappe.tests import IntegrationTestCase

from crm.api.erasure_settings import get_privacy_settings, save_privacy_settings
from crm.privacy.install import setup
from crm.privacy.tests.make_test_user import as_user, make_user

SETTINGS = "CRM Privacy Settings"


class PrivacySettingsCase(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		setup()
		self.admin = make_user("pdr.settings.admin@example.com", roles=["System Manager"])
		self.head = make_user("pdr.settings.head@example.com", roles=["Sales Manager"])

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def current_rows(self) -> list[dict]:
		return get_privacy_settings()["personal_fields"]

	def rows_payload(self, *extra) -> list[dict]:
		rows = [
			{"document_type": r["document_type"], "fieldname": r["fieldname"]} for r in self.current_rows()
		]
		return rows + list(extra)

	def save(self, **values):
		params = {
			"head_of_compliance": None,
			"contract_retention_months": 0,
			"personal_fields": self.rows_payload(),
			**values,
		}
		return as_user(self.admin, save_privacy_settings, **params)

	# --- get
