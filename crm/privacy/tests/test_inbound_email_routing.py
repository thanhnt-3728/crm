# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Routing happens before the insert, so Frappe never pushes the mail to her old lead (M1); notice dedupe (L5)."""

from unittest.mock import patch

import frappe

from crm.privacy.tests.inbound_helpers import COMMUNICATION, EMAIL, LEAD, REQUEST, InboundTestCase
from crm.privacy.tests.make_test_user import block, make_lead, make_request


class RoutingTestCase(InboundTestCase):
	def rooms(self, publish) -> list:
		"""The `(doctype, docname)` every realtime message was addressed to."""
		return [(c.kwargs.get("doctype"), c.kwargs.get("docname")) for c in publish.call_args_list]

	def status(self, mail) -> str:
		return frappe.db.get_value(COMMUNICATION, mail.name, "status")


class TestBeforeInsert(RoutingTestCase):
	def test_a_reply_threaded_onto_her_lead_is_never_published_to_the_lead(self):
		request = make_request(self.logger)
		lead = make_lead(email="someone.else@example.net")

		with patch("frappe.publish_realtime") as publish:
			mail = self.receive(reference_doctype=LEAD, reference_name=lead)

		self.assertNotIn((LEAD, lead), self.rooms(publish))
		self.assertEqual(self.reference(mail), (REQUEST, request))
		self.assertEqual(self.status(mail), "Linked")

	def test_detached_mail_is_never_published_to_the_old_lead_and_is_not_linked(self):
		lead = make_lead(email="someone.else@example.net")
		block(("email", EMAIL))

		with patch("frappe.publish_realtime") as publish:
			mail = self.receive(reference_doctype=LEAD, reference_name=lead)

		self.assertNotIn((LEAD, lead), self.rooms(publish))
		self.assertEqual(self.reference(mail), (None, None))
		self.assertEqual(self.status(mail), "Open")
		self.assertEqual(self.leads_for(), [])

	def test_no_lead_is_created_in_either_case(self):
		make_request(self.logger)
		self.receive()
		block(("email", "erased.person@example.net"))
		self.receive("erased.person@example.net")

		self.assertEqual(self.leads_for(), [])
		self.assertEqual(self.leads_for("erased.person@example.net"), [])

	def test_the_hook_is_registered(self):
		hooks = frappe.get_hooks("doc_events")["Communication"]
		self.assertIn("crm.privacy.inbound_email.route_before_insert", hooks["before_insert"])


class TestNoticeDedupe(RoutingTestCase):
	def test_one_notice_per_erased_sender_per_day(self):
		block(("email", EMAIL), ("email", "second.person@example.net"))

		self.receive()
		self.receive()
		self.assertEqual(len(self.notices()), 1)

		self.receive("second.person@example.net")
		self.assertEqual(len(self.notices()), 2)

	def test_the_same_address_in_another_form_is_the_same_sender(self):
		block(("email", EMAIL))

		self.receive()
		self.receive(" Someone <MARISOL.VEGA@example.com> ")

		self.assertEqual(len(self.notices()), 1)

	def test_a_new_day_notifies_again(self):
		block(("email", EMAIL))
		self.receive()
		frappe.cache.delete_keys("crm_dnc_inbound_notice")  # what the 24 hour expiry does

		self.receive()

		self.assertEqual(len(self.notices()), 2)
