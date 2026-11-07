import frappe
from frappe.email.receive import InboundMail
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime

from crm.fcrm.doctype.crm_deal.test_crm_deal import create_test_contact
from crm.privacy.identifiers import add_do_not_contact
from crm.privacy.inbound import BLOCKED_INBOUND_SUBJECT, is_erasure_address, open_request_for_email
from crm.privacy.tests.factories import (
	make_communication,
	make_compliance_user,
	make_email_account,
	make_request,
)

EMAIL = "marisol@sierrafoothills.example"


class TestInbound(IntegrationTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def test_open_request_receives_mail_and_no_lead(self):
		r = make_request(identifiers=[{"kind": "Email", "value": "marisol@sierrafoothills.example"}])
		c = make_communication(
			sender="Marisol@SierraFoothills.example",
			sent_or_received="Received",
			communication_medium="Email",
			email_account=make_email_account(create_lead_from_incoming_email=1),
		)
		self.assertEqual(
			frappe.db.get_value("Communication", c, ["reference_doctype", "reference_name"]),
			("CRM Erasure Request", r.name),
		)
		self.assertFalse(frappe.db.exists("CRM Lead", {"email": EMAIL}))

	def test_inbound_style_lead_blocked_while_open(self):
		make_request(identifiers=[{"kind": "Email", "value": "marisol@sierrafoothills.example"}])
		lead = frappe.new_doc("CRM Lead")
		lead.email = "marisol@sierrafoothills.example"
		lead.flags.ignore_mandatory = True
		with self.assertRaises(frappe.DuplicateEntryError):
			lead.insert(ignore_permissions=True)

	def test_after_close_mail_stored_unlinked_and_compliance_notified(self):
		officer = make_compliance_user()
		add_do_not_contact("Email", "marisol@sierrafoothills.example", "PDR-0001")
		c = make_communication(
			sender="marisol@sierrafoothills.example",
			sent_or_received="Received",
			communication_medium="Email",
			email_account=make_email_account(create_lead_from_incoming_email=1),
		)
		self.assertTrue(frappe.db.exists("Communication", c))
		self.assertIsNone(frappe.db.get_value("Communication", c, "reference_name"))
		self.assertFalse(frappe.db.exists("CRM Lead", {"email": "marisol@sierrafoothills.example"}))
		self.assertTrue(frappe.db.exists("CRM Notification", {"to_user": officer, "reference_name": c}))

	def _receive(self, **account_fields) -> str:
		"""Run a raw message from her through Frappe's InboundMail, as EmailAccount.receive does."""
		account = frappe.get_doc("Email Account", make_email_account(append_to="CRM Lead", **account_fields))
		raw = (
			"From: Marisol Vega <Marisol@SierraFoothills.example>\r\n"
			"To: inbox@northpine.example\r\n"
			"Subject: About my data\r\n"
			f"Message-ID: <{frappe.generate_hash(length=12)}@sierrafoothills.example>\r\n"
			'Content-Type: text/plain; charset="utf-8"\r\n'
			"\r\n"
			"Hello\r\n"
		)
		return InboundMail(raw, account).process().name

	def test_frappe_inbound_mail_open_request_with_existing_lead(self):
		r = make_request(identifiers=[{"kind": "Email", "value": EMAIL}])
		lead = frappe.get_doc({"doctype": "CRM Lead", "first_name": "Marisol", "email": EMAIL}).insert()
		c = self._receive(create_lead_from_incoming_email=1)
		self.assertEqual(
			frappe.db.get_value("Communication", c, ["reference_doctype", "reference_name"]),
			("CRM Erasure Request", r.name),
		)
		self.assertEqual(frappe.db.count("CRM Lead", {"email": EMAIL}), 1)
		self.assertFalse(frappe.db.exists("Communication", {"reference_name": lead.name}))

	def test_frappe_inbound_mail_open_request_creates_no_lead(self):
		r = make_request(identifiers=[{"kind": "Email", "value": EMAIL}])
		c = self._receive()
		self.assertEqual(frappe.db.get_value("Communication", c, "reference_name"), r.name)
		self.assertFalse(frappe.db.exists("CRM Lead", {"email": EMAIL}))

	def test_frappe_inbound_mail_blocked_sender_stored_unlinked(self):
		add_do_not_contact("Email", EMAIL, "PDR-0001")
		c = self._receive(create_lead_from_incoming_email=1)
		self.assertEqual(
			frappe.db.get_value("Communication", c, ["reference_doctype", "reference_name"]), (None, None)
		)
		self.assertFalse(frappe.db.exists("CRM Lead", {"email": EMAIL}))

	def test_blocked_notification_names_the_request_not_the_sender(self):
		officer = make_compliance_user()
		r = make_request(identifiers=[{"kind": "Email", "value": "someone.else@example.com"}])
		add_do_not_contact("Email", EMAIL, r.name)
		c = make_communication(
			sender=EMAIL,
			sent_or_received="Received",
			communication_medium="Email",
			email_account=make_email_account(),
		)
		note = frappe.db.get_value(
			"CRM Notification",
			{"to_user": officer, "reference_name": c},
			["notification_text", "notification_type_doc", "reference_doctype"],
			as_dict=True,
		)
		self.assertEqual(note.notification_text, BLOCKED_INBOUND_SUBJECT)
		self.assertEqual(note.notification_type_doc, r.name)
		self.assertEqual(note.reference_doctype, "Communication")
		self.assertNotIn("marisol", note.notification_text.lower())

	def test_open_request_mail_kept_off_her_records_timeline(self):
		r = make_request(identifiers=[{"kind": "Email", "value": EMAIL}])
		contact = create_test_contact(first_name="Marisol", last_name="Vega", email=EMAIL)
		c = make_communication(
			sender=EMAIL,
			sent_or_received="Received",
			communication_medium="Email",
			email_account=make_email_account(),
		)
		self.assertEqual(frappe.db.get_value("Communication", c, "reference_name"), r.name)
		self.assertFalse(
			frappe.db.exists(
				"Communication Link", {"parent": c, "link_doctype": "Contact", "link_name": contact.name}
			)
		)

	def _new_error_logs(self, since) -> list[str]:
		"""Error Logs written since `since`. Error Log lives in the SQLite log store, which
		rollback doesn't reach, so the rows are also deleted at cleanup."""
		names = frappe.get_all("Error Log", filters={"creation": [">=", since]}, pluck="name")
		for name in names:
			self.addCleanup(frappe.delete_doc, "Error Log", name, ignore_permissions=True)
		return names

	def test_blocked_sender_no_contact_auto_created_and_no_error_log(self):
		started = now_datetime()
		add_do_not_contact("Email", EMAIL, "PDR-0001")
		c = self._receive(create_lead_from_incoming_email=1, create_contact=1)
		self.assertTrue(frappe.db.exists("Communication", c))
		self.assertFalse(frappe.db.exists("Contact Email", {"email_id": EMAIL}))
		self.assertFalse(frappe.db.exists("Communication Link", {"parent": c, "link_doctype": "Contact"}))
		self.assertEqual(self._new_error_logs(started), [])

	def test_open_request_no_contact_for_her_but_co_recipient_still_created(self):
		started = now_datetime()
		make_request(identifiers=[{"kind": "Email", "value": EMAIL}])
		c = make_communication(
			sender=EMAIL,
			recipients="inbox@northpine.example",
			cc="Theo Brandt <Theo.Brandt@pinecrest-dental.example>",
			sent_or_received="Received",
			communication_medium="Email",
			email_account=make_email_account(create_contact=1),
		)
		self.assertTrue(frappe.db.exists("Communication", c))
		self.assertFalse(frappe.db.exists("Contact Email", {"email_id": EMAIL}))
		self.assertTrue(
			frappe.db.exists("Contact Email", {"email_id": "Theo.Brandt@pinecrest-dental.example"})
		)
		self.assertEqual(self._new_error_logs(started), [])

	def test_contact_auto_create_unchanged_for_other_senders(self):
		make_request(identifiers=[{"kind": "Email", "value": EMAIL}])
		c = make_communication(
			sender="Theo.Brandt@pinecrest-dental.example",
			sent_or_received="Received",
			communication_medium="Email",
			email_account=make_email_account(create_contact=1),
		)
		contact = frappe.db.get_value(
			"Contact Email", {"email_id": "Theo.Brandt@pinecrest-dental.example"}, "parent"
		)
		self.assertTrue(contact)
		self.assertTrue(
			frappe.db.exists(
				"Communication Link", {"parent": c, "link_doctype": "Contact", "link_name": contact}
			)
		)

	def test_sent_mail_and_unrelated_senders_untouched(self):
		make_request(identifiers=[{"kind": "Email", "value": EMAIL}])
		sent = make_communication(sender=EMAIL, email_account=make_email_account())
		self.assertIsNone(frappe.db.get_value("Communication", sent, "reference_doctype"))
		other = make_communication(
			sender="someone.else@example.com",
			sent_or_received="Received",
			communication_medium="Email",
		)
		self.assertIsNone(frappe.db.get_value("Communication", other, "reference_doctype"))

	def test_open_request_lookup_skips_closed_and_excluded(self):
		closed = make_request(identifiers=[{"kind": "Email", "value": EMAIL}])
		frappe.db.set_value("CRM Erasure Request", closed.name, "status", "Closed")
		excluded = make_request(identifiers=[{"kind": "Email", "value": EMAIL, "excluded": 1}])
		self.assertIsNone(open_request_for_email(EMAIL))
		self.assertFalse(is_erasure_address(EMAIL))

		older = make_request(identifiers=[{"kind": "Email", "value": EMAIL}])
		newer = make_request(identifiers=[{"kind": "Email", "value": EMAIL}])
		self.assertEqual(open_request_for_email(" Marisol@SierraFoothills.example "), newer.name)
		self.assertEqual(open_request_for_email("Marisol Vega <Marisol@SierraFoothills.example>"), newer.name)
		self.assertTrue(is_erasure_address(EMAIL))
		self.assertNotIn(excluded.name, (older.name, newer.name))

	def test_blocked_address_is_erasure_address(self):
		self.assertFalse(is_erasure_address(EMAIL))
		add_do_not_contact("Email", EMAIL, "PDR-0001")
		self.assertTrue(is_erasure_address(EMAIL))

	def test_guard_ignores_leads_inserted_without_ignore_mandatory(self):
		make_request(identifiers=[{"kind": "Email", "value": EMAIL}])
		lead = frappe.new_doc("CRM Lead")
		lead.first_name = "Marisol"
		lead.email = EMAIL
		lead.insert(ignore_permissions=True)
		self.assertTrue(frappe.db.exists("CRM Lead", lead.name))
