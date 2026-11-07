# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The Marisol scenario builds, and sits in the state the phase 05 tests start from."""

import os

import frappe

from crm.privacy.tests.erasure_fixture import ErasureTestCase
from crm.privacy.tests.make_test_user import match_rows


class TestErasureFixture(ErasureTestCase):
	def test_the_request_is_ready_for_sign_off(self):
		doc = frappe.get_doc("CRM Erasure Request", self.request)
		self.assertEqual(doc.status, "Awaiting sign-off")
		rows = match_rows(self.request)
		self.assertTrue(rows[("CRM Lead", self.p.lead)].confirmed)
		self.assertTrue(rows[("Contact", self.p.contact)].confirmed)
		self.assertTrue(rows[("CRM Deal", self.p.won)].confirmed)
		self.assertEqual(rows[("CRM Deal", self.p.removed)].relation, "Removed from open deal")
		self.assertFalse(rows[("CRM Deal", self.p.copy_deal)].confirmed)
		self.assertNotIn(("CRM Lead", self.p.lookalike), rows)
		excluded = {i.value for i in doc.identifiers if i.excluded}
		self.assertEqual(excluded, {self.p.shared_email})

	def test_the_files_are_on_disk(self):
		self.assertEqual(len(self.paths), 6)  # + the WhatsApp voice note
		for path in self.paths:
			self.assertTrue(os.path.exists(path), path)

	def test_the_on_hold_notice_and_its_queued_mail_exist(self):
		self.assertTrue(
			frappe.db.exists(
				"CRM Notification",
				{"notification_type_doctype": "CRM Erasure Request", "notification_type_doc": self.request},
			)
		)
		self.assertTrue(
			frappe.db.exists(
				"Email Queue", {"reference_doctype": "CRM Erasure Request", "reference_name": self.request}
			)
		)

	def test_the_custom_field_holds_a_value_outside_the_list(self):
		self.assertEqual(frappe.db.get_value("CRM Lead", self.p.lead, "personal_mobile"), "+15305550104")
