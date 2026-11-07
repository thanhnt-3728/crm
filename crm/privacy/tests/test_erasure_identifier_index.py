# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Every received mail joins on `CRM Erasure Identifier.normalized` (`inbound_email.open_request_for`), so the column
is indexed."""

import frappe
from frappe.tests import IntegrationTestCase


class TestIdentifierIndex(IntegrationTestCase):
	def test_normalized_is_indexed(self):
		rows = frappe.db.sql(
			"show index from `tabCRM Erasure Identifier` where Column_name = 'normalized'", as_dict=True
		)
		self.assertTrue(rows)
