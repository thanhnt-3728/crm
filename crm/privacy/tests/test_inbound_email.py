# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Inbound email from a person with an open request or on the do-not-contact list (design 5.9)."""

import frappe

from crm.privacy.request_status import server_write
from crm.privacy.tests.inbound_helpers import (
	COMMUNICATION,
	EMAIL,
	LEAD,
	NOTICE,
	REQUEST,
	InboundTestCase,
)
from crm.privacy.tests.make_test_user import block, force_request, make_lead, make_request


class TestOpenRequest(InboundTestCase):
	def test_mail_from_a_confirmed_email_is_attached_to_the_request_and_starts_no_lead(self):
		request = make_request(self.logger)

		doc = self.receive()

		self.assertEqual(self.reference(doc), (REQUEST, request))
		self.assertEqual((doc.reference_doctype, doc.reference_name), (REQUEST, request))
		self.assertEqual(self.leads_for(), [])

	def test_every_open_status_attaches_it(self):
		request = make_request(self.logger)
		for status in ("Logged", "Awaiting sign-off", "On Hold", "Erased"):
			force_request(request, status=status)

			doc = self.receive()

			self.assertEqual(self.reference(doc), (REQUEST, request), status)

	def test_a_declined_or_closed_request_attaches_nothing(self):
		request = make_request(self.logger)
		for status in ("Declined", "Closed"):
			force_request(request, status=status)

			doc = self.receive()

			self.assertNotEqual(self.reference(doc)[0], REQUEST, status)
			frappe.db.delete(LEAD, {"email": EMAIL})

	def test_an_excluded_identifier_does_not_match(self):
		request = make_request(self.logger)
		doc = frappe.get_doc(REQUEST, request)
		doc.identifiers[0].excluded = 1
		with server_write():
			doc.save(ignore_permissions=True)

		mail = self.receive()

		self.assertEqual(self.reference(mail), (LEAD, self.leads_for()[0]))

	def test_a_reply_threaded_onto_her_lead_is_moved_to_the_request(self):
		request = make_request(self.logger)
		lead = make_lead(email="someone.else@example.net")

		doc = self.receive(reference_doctype=LEAD, reference_name=lead)

		self.assertEqual(self.reference(doc), (REQUEST, request))
		self.assertEqual(doc.reference_doctype, REQUEST)

	def test_the_newest_open_request_wins_when_two_list_the_address(self):
		make_request(self.logger)
		newer = make_request(self.logger)

		self.assertEqual(self.reference(self.receive()), (REQUEST, newer))

	def test_another_sender_is_unchanged(self):
		make_request(self.logger)

		doc = self.receive("Someone Else <someone.else@example.net>")

		self.assertEqual(self.reference(doc)[0], LEAD)
		self.assertEqual(self.leads_for("someone.else@example.net"), [self.reference(doc)[1]])

	def test_sent_mail_is_left_alone(self):
		request = make_request(self.logger)

		doc = self.receive(sent_or_received="Sent")

		self.assertNotEqual(self.reference(doc), (REQUEST, request))


class TestDoNotContactList(InboundTestCase):
	def test_mail_from_an_erased_address_starts_no_lead_and_compliance_is_told(self):
		block(("email", EMAIL))

		doc = self.receive()

		self.assertEqual(self.reference(doc), (None, None))
		self.assertEqual(self.leads_for(), [])
		(notice,) = self.notices()
		self.assertEqual((notice.reference_doctype, notice.reference_name), (COMMUNICATION, doc.name))
		self.assertEqual(notice.notification_text, NOTICE)

	def test_a_reply_threaded_onto_the_old_lead_is_detached(self):
		lead = make_lead(email="someone.else@example.net")
		block(("email", EMAIL))

		doc = self.receive(reference_doctype=LEAD, reference_name=lead)

		self.assertEqual(self.reference(doc), (None, None))
		self.assertEqual((doc.reference_doctype, doc.reference_name), (None, None))
		self.assertEqual(len(self.notices()), 1)

	def test_the_notice_names_no_address(self):
		block(("email", EMAIL))

		self.receive()

		for notice in self.notices():
			self.assertNotIn("marisol", notice.notification_text.lower())
			self.assertNotIn("example", notice.notification_text.lower())

	def test_after_close_the_mail_goes_to_the_list_not_the_request(self):
		request = make_request(self.logger)
		force_request(request, status="Closed")
		block(("email", EMAIL))

		doc = self.receive()

		self.assertEqual(self.reference(doc), (None, None))
		self.assertEqual(len(self.notices()), 1)

	def test_an_open_request_wins_over_the_list(self):
		request = make_request(self.logger)
		block(("email", EMAIL))

		doc = self.receive()

		self.assertEqual(self.reference(doc), (REQUEST, request))
		self.assertEqual(self.notices(), [])

	def test_another_sender_is_unchanged(self):
		block(("email", EMAIL))

		doc = self.receive("someone.else@example.net")

		self.assertEqual(self.reference(doc)[0], LEAD)
		self.assertEqual(self.notices(), [])
