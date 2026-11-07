# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Compliance reads the inbound mail it is told about, through two endpoints and nothing broader (design 5.9)."""

import frappe

from crm.api.erasure_inbound import get_inbound_communication, list_request_communications
from crm.privacy.do_not_contact import PrivacySettingsIncompleteError
from crm.privacy.tests.inbound_helpers import COMMUNICATION, EMAIL, REQUEST, InboundTestCase
from crm.privacy.tests.make_test_user import as_user, block, forget_dnc_secret, make_lead, make_request

SUBJECT = "Please remove me"


class TestInboundApi(InboundTestCase):
	def attached(self):
		request = make_request(self.logger)
		return request, self.receive(subject=SUBJECT)

	def detached(self):
		block(("email", EMAIL))
		return self.receive(subject=SUBJECT)

	def test_mailbox_sync_owns_the_mail_so_the_standard_permission_denies_everyone_else(self):
		request, mail = self.attached()

		self.assertEqual(frappe.db.get_value(COMMUNICATION, mail.name, "owner"), "Administrator")
		for user in (self.logger, self.other, self.manager, self.compliance):
			self.assertFalse(frappe.has_permission(COMMUNICATION, "read", doc=mail.name, user=user), user)

	def test_compliance_reads_mail_attached_to_a_request(self):
		request, mail = self.attached()

		doc = as_user(self.compliance, get_inbound_communication, mail.name)

		self.assertEqual(doc["name"], mail.name)
		self.assertEqual(doc["subject"], SUBJECT)
		self.assertIn("call me back", doc["content"])
		self.assertEqual((doc["reference_doctype"], doc["reference_name"]), (REQUEST, request))
		self.assertEqual(doc["sender"], mail.sender)
		for key in ("recipients", "communication_date"):
			self.assertIn(key, doc)

	def test_compliance_lists_the_mail_of_a_request(self):
		request, mail = self.attached()
		make_request(self.logger)  # another request, no mail

		rows = as_user(self.compliance, list_request_communications, request)

		self.assertEqual([row["name"] for row in rows], [mail.name])
		self.assertEqual(rows[0]["subject"], SUBJECT)
		self.assertEqual(as_user(self.compliance, list_request_communications, make_request(self.logger)), [])

	def test_compliance_reads_the_detached_mail_it_is_notified_about(self):
		mail = self.detached()
		(notice,) = self.notices()

		doc = as_user(self.compliance, get_inbound_communication, notice.reference_name)

		self.assertEqual(notice.reference_name, mail.name)
		self.assertEqual(doc["subject"], SUBJECT)
		self.assertIsNone(doc["reference_name"])

	def test_everyone_but_compliance_is_refused(self):
		request, attached = self.attached()
		detached = self.detached()

		for user in (self.logger, self.other, self.manager, "Administrator"):
			for mail in (attached, detached):
				with self.assertRaises(frappe.PermissionError, msg=user):
					as_user(user, get_inbound_communication, mail.name)
			with self.assertRaises(frappe.PermissionError, msg=user):
				as_user(user, list_request_communications, request)

	def test_a_communication_that_is_not_erasure_mail_is_refused_even_for_compliance(self):
		block(("email", EMAIL))
		lead = make_lead(email="someone.else@example.net")
		linked = self.receive("someone.else@example.net", reference_doctype="CRM Lead", reference_name=lead)
		frappe.db.set_value("Email Account", self.account, "create_lead_from_incoming_email", 0)
		loose = self.receive("loose.sender@example.net")  # no lead, no reference, sender not erased
		sent = self.receive(sent_or_received="Sent")  # sent to the erased address, so not inbound mail

		for mail in (linked, loose, sent):
			with self.assertRaises(frappe.PermissionError, msg=mail.name):
				as_user(self.compliance, get_inbound_communication, mail.name)

	def test_a_missing_name_is_not_found(self):
		with self.assertRaises(frappe.DoesNotExistError):
			as_user(self.compliance, get_inbound_communication, "no-such-mail")
		with self.assertRaises(frappe.DoesNotExistError):
			as_user(self.compliance, list_request_communications, "PDR-9999")

	def test_a_detached_mail_cannot_be_judged_without_the_secret(self):
		mail = self.detached()
		forget_dnc_secret()

		with self.assertRaises(PrivacySettingsIncompleteError):
			as_user(self.compliance, get_inbound_communication, mail.name)
