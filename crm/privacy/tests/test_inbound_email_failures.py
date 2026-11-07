# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Inbound email must never be rejected, whatever the privacy check does (design 5.9, RT-15, V1)."""

from unittest.mock import patch

import frappe

from crm.privacy.tests.inbound_helpers import (
	COMMUNICATION,
	EMAIL,
	LEAD,
	REQUEST,
	SENDER,
	InboundTestCase,
)
from crm.privacy.tests.make_test_user import (
	block,
	forget_dnc_secret,
	make_lead,
	make_request,
	purge_logs_titled,
)

INBOUND = "crm.privacy.inbound_email"
OTHER = "someone.else@example.net"


class FailureTestCase(InboundTestCase):
	def tearDown(self):
		frappe.db.rollback()
		for prefix in ("Inbound email privacy check", "DNC secret unavailable", "Unable to add contact"):
			purge_logs_titled(self._started, prefix)
		frappe.db.commit()
		super().tearDown()

	def logs(self, prefix: str) -> list:
		return frappe.get_all(
			"Error Log", {"method": ["like", f"{prefix}%"], "creation": [">=", self._started]}, ["method", "error"]
		)


class TestTheCheckFails(FailureTestCase):
	def test_an_error_in_the_check_keeps_the_mail_and_starts_no_lead(self):
		messages_before = len(frappe.local.message_log)

		with patch(f"{INBOUND}.open_request_for", side_effect=RuntimeError("boom for marisol.vega")):
			doc = self.receive()

		self.assertTrue(frappe.db.exists(COMMUNICATION, doc.name))
		self.assertEqual(self.leads_for(), [])
		self.assertEqual(len(frappe.local.message_log), messages_before)
		(log,) = self.logs("Inbound email privacy check")
		self.assertEqual((log.method, log.error), ("Inbound email privacy check", "RuntimeError"))

	def test_a_failed_notice_does_not_undo_the_detach(self):
		lead = make_lead(email=OTHER)
		block(("email", EMAIL))

		with patch(f"{INBOUND}.notify_compliance", side_effect=RuntimeError):
			doc = self.receive(reference_doctype=LEAD, reference_name=lead)

		self.assertEqual(self.reference(doc), (None, None))
		self.assertEqual(self.leads_for(), [])
		(log,) = self.logs("Inbound email privacy check")
		self.assertEqual((log.method, log.error), ("Inbound email privacy check: notice", "RuntimeError"))

	def test_a_mailbox_that_creates_contacts_keeps_the_mail_and_logs_no_address(self):
		"""Email Account.create_contact is on by default: Frappe tries to create a Contact for the sender, the
		block refuses, Frappe logs "Unable to add contact" with a traceback and the contact name."""
		frappe.db.set_value("Email Account", self.account, "create_contact", 1)
		block(("email", EMAIL))

		doc = self.receive()

		self.assertTrue(frappe.db.exists(COMMUNICATION, doc.name))
		self.assertFalse(frappe.db.exists("Contact Email", {"email_id": EMAIL}))
		logs = frappe.get_all(
			"Error Log",
			{"method": "Unable to add contact", "creation": [">=", self._started]},
			["error", "reference_name"],
		)
		self.assertTrue(logs)
		for log in logs:
			self.assertEqual(log.error, "ErasedPersonBlockedError")
			self.assertIsNone(log.reference_name)
		self.assertFalse(frappe.get_all("Error Log", {"error": ["like", "%marisol%"]}))
		purge_logs_titled(self._started, "Unable to add contact")  # Frappe's log outlives the rollback


class TestSecretMissing(FailureTestCase):
	def setUp(self):
		super().setUp()
		block(("email", OTHER))
		forget_dnc_secret()

	def test_the_mail_is_kept_starts_no_lead_and_compliance_hears_once_a_day(self):
		first, second = self.receive("a.sender@example.net"), self.receive("b.sender@example.net")

		for doc in (first, second):
			self.assertTrue(frappe.db.exists(COMMUNICATION, doc.name))
			self.assertEqual(self.reference(doc), (None, None))
		self.assertEqual(frappe.get_all(LEAD, {"email": ["like", "%.sender@example.net"]}), [])
		self.assertEqual(frappe.local.message_log, [])
		self.assertEqual(len(self.notices()), 1)
		logs = self.logs("DNC secret unavailable")
		self.assertEqual({(log.method, log.error) for log in logs}, {
			("DNC secret unavailable: inbound email", "DncSecretUnavailableError")
		})

	def test_an_open_request_still_matches_because_it_needs_no_secret(self):
		request = make_request(self.logger)

		doc = self.receive(SENDER)

		self.assertEqual(self.reference(doc), (REQUEST, request))
		self.assertEqual(self.notices(), [])
