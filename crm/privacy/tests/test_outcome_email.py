# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""`send_outcome_email`: Compliance answers the requester from the request without any broad email permission
(phase 07 fix round; safety-critical: personal data leaves the CRM)."""

import frappe

from crm.api.erasure_outcome_email import send_outcome_email
from crm.api.erasure_review import close_request
from crm.privacy.request_status import server_write
from crm.privacy.tests.close_fixture import EMAIL, CloseTestCase, force_request
from crm.privacy.tests.make_test_user import as_user, make_contact

DOCTYPE = "CRM Erasure Request"
SUBJECT, BODY = "Your request to erase your personal data", "<p>We erased your data. No exceptions.</p>"


def make_outgoing_account() -> None:
	if frappe.db.exists("Email Account", {"default_outgoing": 1}):
		return
	account = frappe.get_doc(
		{
			"doctype": "Email Account",
			"email_account_name": f"Outcome out {frappe.generate_hash(length=6)}",
			"email_id": f"outcome-{frappe.generate_hash(length=6)}@example.org",
			"enable_outgoing": 1,
			"default_outgoing": 1,
			"smtp_server": "localhost",
		}
	)
	account.flags.ignore_mandatory = True
	account.flags.ignore_validate = True
	account.insert(ignore_permissions=True)


def mails_of(request: str) -> list[str]:
	return frappe.get_all(
		"Communication", {"reference_doctype": DOCTYPE, "reference_name": request}, pluck="name"
	)


class OutcomeEmailCase(CloseTestCase):
	def setUp(self):
		super().setUp()
		make_outgoing_account()
		self.before = set(mails_of(self.request))

	def send(self, user=None, **values):
		params = {
			"name": self.request,
			"subject": SUBJECT,
			"content": BODY,
			"recipients": [EMAIL],
			**values,
		}
		return as_user(user or self.compliance, send_outcome_email, **params)

	def new_mails(self) -> list[str]:
		return sorted(set(mails_of(self.request)) - self.before)


class TestWhoMaySend(OutcomeEmailCase):
	def test_a_sales_user_sales_manager_and_the_logger_are_refused(self):
		for user in (self.other, self.manager, self.logger):
			with self.subTest(user=user), self.assertRaises(frappe.PermissionError):
				self.send(user)
		self.assertEqual(self.new_mails(), [])

	def test_administrator_without_an_explicit_compliance_row_is_refused(self):
		with self.assertRaises(frappe.PermissionError):
			self.send("Administrator")
		self.assertEqual(self.new_mails(), [])


class TestWhenAndToWhom(OutcomeEmailCase):
	def test_only_an_erased_or_declined_request_may_be_answered(self):
		for status in ("Logged", "Awaiting sign-off", "On Hold", "Closed"):
			force_request(self.request, status=status)
			with self.subTest(status=status), self.assertRaises(frappe.ValidationError):
				self.send()
		self.assertEqual(self.new_mails(), [])

	def test_a_declined_request_may_be_answered(self):
		force_request(self.request, status="Declined")
		self.send()
		self.assertEqual(len(self.new_mails()), 1)

	def test_a_running_job_refuses(self):
		for job in ("Queued", "Running"):
			force_request(self.request, erasure_job_status=job)
			with self.subTest(job=job), self.assertRaises(frappe.ValidationError):
				self.send()
		self.assertEqual(self.new_mails(), [])

	def test_a_recipient_outside_the_request_is_refused(self):
		for recipients in (["stranger@example.com"], [EMAIL, "stranger@example.com"], ["x@y.com, " + EMAIL]):
			with self.subTest(recipients=recipients), self.assertRaises(frappe.ValidationError):
				self.send(recipients=recipients)
		self.assertEqual(self.new_mails(), [])

	def test_an_excluded_identifier_is_not_a_recipient(self):
		doc = frappe.get_doc(DOCTYPE, self.request)
		for row in doc.identifiers:
			if row.value == EMAIL:
				row.excluded = 1
		with server_write():
			doc.save(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			self.send()
		self.assertEqual(self.new_mails(), [])

	def test_no_recipient_empty_subject_or_empty_body_is_refused(self):
		for values in ({"recipients": []}, {"subject": "  "}, {"content": ""}):
			with self.subTest(values=values), self.assertRaises(frappe.ValidationError):
				self.send(**values)
		self.assertEqual(self.new_mails(), [])

	def test_the_address_match_ignores_case_and_spaces(self):
		self.send(recipients=[f"  {EMAIL.upper()} "])
		self.assertEqual(len(self.new_mails()), 1)


class TestWhatItCreates(OutcomeEmailCase):
	def test_one_communication_linked_to_the_request_and_one_queue_row(self):
		queued_before = set(frappe.get_all("Email Queue", pluck="name"))
		self.send()
		mails = self.new_mails()
		self.assertEqual(len(mails), 1)
		mail = frappe.get_doc("Communication", mails[0])
		self.assertEqual((mail.reference_doctype, mail.reference_name), (DOCTYPE, self.request))
		self.assertEqual(mail.sent_or_received, "Sent")
		self.assertEqual(mail.subject, SUBJECT)
		queued = set(frappe.get_all("Email Queue", {"communication": mails[0]}, pluck="name"))
		self.assertEqual(len(queued - queued_before), 1)

	def test_the_email_is_not_timeline_linked_to_the_requesters_contact(self):
		"""A Declined request leaves her Contact alone; a link would show the answer on its timeline."""
		contact = make_contact("Marisol", emails=[EMAIL])
		force_request(self.request, status="Declined")
		self.send()
		(mail,) = self.new_mails()
		links = frappe.get_all(
			"Communication Link", {"parent": mail}, ["link_doctype", "link_name"], as_list=True
		)
		self.assertEqual([link for link in links if link != (DOCTYPE, self.request)], [])
		self.assertFalse(
			frappe.db.exists("Communication Link", {"link_doctype": "Contact", "link_name": contact})
		)

	def test_the_endpoint_grants_nothing_on_communication(self):
		self.send()
		frappe.set_user(self.compliance)
		try:
			self.assertFalse(frappe.has_permission("Communication", "create"))
			self.assertFalse(frappe.has_permission(DOCTYPE, "email", self.request))
		finally:
			frappe.set_user("Administrator")


class TestCloseAfterTheOutcomeEmail(OutcomeEmailCase):
	def close(self):
		return as_user(self.compliance, close_request, self.request, frappe.utils.today(), "Completed", None)

	def test_close_is_refused_until_the_mail_is_sent_then_goes_through(self):
		self.send()
		(mail,) = self.new_mails()
		queued = frappe.get_all("Email Queue", {"communication": mail}, pluck="name")
		self.assertEqual(frappe.db.get_value("Email Queue", queued[0], "status"), "Not Sent")
		with self.assertRaises(frappe.ValidationError):
			self.close()
		frappe.db.set_value("Email Queue", queued[0], "status", "Sent")
		self.assertEqual(self.close()["status"], "Closed")
		self.assertEqual(mails_of(self.request), [])  # closing detaches and scrubs every email of the request
