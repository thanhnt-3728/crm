# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""`approved_plan_hash` and `pending_file_deletions` (file paths that can carry her name) sit at permlevel 1 that no
role can read, so the generic client API never returns them (L8); the server still reads and writes them."""

import frappe

from crm.privacy.request_visibility import INTERNAL_FIELDS
from crm.privacy.tests.make_test_user import RequestTestCase, as_user, force_request

DOCTYPE = "CRM Erasure Request"
FILES = '[["/files/marisol-vega-call.mp3", "public"]]'


class TestInternalFieldsAreHidden(RequestTestCase):
	def setUp(self):
		super().setUp()
		self.name = self.submitted_request()
		force_request(self.name, approved_plan_hash="abc123", pending_file_deletions=FILES)

	def get(self, user: str) -> dict:
		return as_user(user, frappe.client.get, DOCTYPE, self.name)

	def test_frappe_client_get_returns_neither_field_to_compliance_or_the_manager(self):
		for user in (self.compliance, self.manager):
			got = self.get(user)
			self.assertEqual(got.name, self.name)
			for field in INTERNAL_FIELDS:
				self.assertIsNone(got.get(field), f"{field} returned to {user}")

	def test_frappe_client_get_returns_neither_field_to_the_logger(self):
		force_request(self.name, status="Logged")
		got = self.get(self.logger)
		self.assertEqual(got.name, self.name)
		for field in INTERNAL_FIELDS:
			self.assertIsNone(got.get(field))

	def test_get_value_does_not_return_them_either(self):
		for field in INTERNAL_FIELDS:
			got = as_user(self.compliance, frappe.client.get_value, DOCTYPE, field, self.name)
			self.assertNotIn(field, got or {})

	def test_the_server_still_reads_both(self):
		doc = frappe.get_doc(DOCTYPE, self.name)
		self.assertEqual((doc.approved_plan_hash, doc.pending_file_deletions), ("abc123", FILES))
