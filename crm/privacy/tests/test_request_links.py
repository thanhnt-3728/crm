# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Link validation on a request is skipped only for the server's own writes (M6)."""

import frappe

from crm.privacy.request_status import server_write
from crm.privacy.tests.make_test_user import (
	RequestTestCase,
	add_match,
	make_lead,
	make_request,
	match_rows,
)


class TestRequestLinks(RequestTestCase):
	def dangling(self):
		gone = make_lead(first_name="Gone", email="gone@example.com")
		name = make_request(self.logger)
		add_match(name, "CRM Lead", gone)
		frappe.delete_doc("CRM Lead", gone, force=True)
		return name, gone

	def test_a_generic_save_with_a_bogus_link_still_fails_the_link_check(self):
		name = make_request(self.logger)
		doc = frappe.get_doc("CRM Erasure Request", name)
		doc.approver = "nobody@nowhere.example"
		with self.assertRaises(frappe.LinkValidationError):
			doc.save(ignore_permissions=True)

	def test_a_server_write_may_save_a_match_row_whose_record_is_gone(self):
		name, gone = self.dangling()
		doc = frappe.get_doc("CRM Erasure Request", name)
		doc.requester_names = "Edited"
		with server_write():
			doc.save(ignore_permissions=True)
		self.assertIn(("CRM Lead", gone), match_rows(name))

	def test_a_generic_save_of_a_request_with_a_dangling_row_keeps_link_validation(self):
		name, _gone = self.dangling()
		doc = frappe.get_doc("CRM Erasure Request", name)
		doc.requester_names = "Edited"
		with self.assertRaises(frappe.LinkValidationError):
			doc.save(ignore_permissions=True)
