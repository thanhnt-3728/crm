# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from crm.api.whatsapp import validate as validate_whatsapp_message
from crm.fcrm.doctype.crm_erasure_request.test_crm_erasure_request import make_request, make_user
from crm.lead_syncing.doctype.lead_sync_source.facebook import FacebookSyncSource
from crm.privacy.identifiers import add_do_not_contact
from crm.privacy.inbound import on_whatsapp_insert
from crm.privacy.setup import ensure_privacy_setup
from crm.tests.test_privacy_matching import ensure_deal_status
from crm.utils import create_lead_from_incoming_email

SAVEPOINT = "test_privacy_blocking"
COMPLIANCE_USER = "blocking-compliance@example.com"
ERASED = "marisol@x.net"
MESSAGE = "asked to be erased"


def make_lead(**values):
	lead = frappe.get_doc({"doctype": "CRM Lead", "first_name": "M", **values})
	lead.flags.ignore_mandatory = True
	return lead.insert(ignore_permissions=True)


def make_contact(email, phone=None, first_name="Marisol"):
	return frappe.get_doc(
		{
			"doctype": "Contact",
			"first_name": first_name,
			"email_ids": [{"email_id": email, "is_primary": 1}],
			"phone_nos": [{"phone": phone, "is_primary_mobile_no": 1}] if phone else [],
		}
	).insert(ignore_permissions=True)


def make_deal(contact_rows):
	deal = frappe.get_doc(
		{
			"doctype": "CRM Deal",
			"organization": "Blocking Test Org",
			"status": ensure_deal_status("Blocking Open", "Open"),
			"contacts": contact_rows,
		}
	)
	deal.flags.ignore_mandatory = True
	deal.flags.ignore_links = True
	return deal


def make_email(sender, **values):
	return frappe.get_doc(
		{
			"doctype": "Communication",
			"communication_type": "Communication",
			"communication_medium": "Email",
			"sent_or_received": "Received",
			"sender": sender,
			"subject": "Hello",
			"content": "Hello",
			**values,
		}
	)


class TestPrivacyBlocking(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_privacy_setup()
		make_user(COMPLIANCE_USER, ["Sales User", "Compliance"])

	def setUp(self):
		frappe.db.savepoint(SAVEPOINT)
		frappe.db.delete("CRM Do Not Contact")
		# Phone numbers below are typed without a country code, so the site region must be US.
		frappe.db.set_single_value("System Settings", "country", "United States")

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.flags.privacy_system_write = False
		frappe.db.rollback(save_point=SAVEPOINT)

	# -- blocking ---------------------------------------------------------------------------

	def test_new_lead_blocked(self):
		add_do_not_contact("Email", ERASED)
		with self.assertRaisesRegex(frappe.ValidationError, MESSAGE):
			frappe.get_doc({"doctype": "CRM Lead", "first_name": "M", "email": "MARISOL@x.net"}).insert()
		self.assertFalse(frappe.db.exists("CRM Lead", {"email": "MARISOL@x.net"}))

	def test_phone_format_blocked(self):
		add_do_not_contact("Phone", "+19165550100")
		for field in ("mobile_no", "phone"):
			with self.assertRaisesRegex(frappe.ValidationError, MESSAGE):
				frappe.get_doc({"doctype": "CRM Lead", "first_name": "M", field: "(916) 555-0100"}).insert()

	def test_unrelated_lead_is_not_blocked(self):
		add_do_not_contact("Email", ERASED)
		lead = make_lead(email="someone.else@x.net", mobile_no="(916) 555-0199")
		self.assertTrue(frappe.db.exists("CRM Lead", lead.name))

	def test_existing_record_saves_if_unchanged(self):
		lead = make_lead(email=ERASED, mobile_no="+19165550100")
		add_do_not_contact("Email", ERASED)
		add_do_not_contact("Phone", "+19165550100")

		lead.reload()
		lead.first_name = "Renamed"
		lead.save(ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("CRM Lead", lead.name, "first_name"), "Renamed")

	def test_changing_existing_record_to_blocked_value_refused(self):
		lead = make_lead(email="someone.else@x.net")
		add_do_not_contact("Email", ERASED)

		lead.reload()
		lead.email = " Marisol@X.net "
		with self.assertRaisesRegex(frappe.ValidationError, MESSAGE):
			lead.save(ignore_permissions=True)

	def test_deal_contact_row_blocked(self):
		contact = make_contact("someone.else@x.net")
		add_do_not_contact("Email", ERASED)
		add_do_not_contact("Phone", "+19165550100")

		deal = make_deal([{"contact": contact.name, "email": "MARISOL@x.net"}])
		with self.assertRaisesRegex(frappe.ValidationError, MESSAGE):
			deal.insert(ignore_permissions=True)

		deal = make_deal([{"contact": contact.name, "phone": "(916) 555-0100"}])
		with self.assertRaisesRegex(frappe.ValidationError, MESSAGE):
			deal.insert(ignore_permissions=True)

	def test_deal_new_contact_row_blocked_but_existing_rows_kept(self):
		contact = make_contact("someone.else@x.net")
		other = make_contact("third@x.net", first_name="Third")
		deal = make_deal([{"contact": contact.name, "email": ERASED}]).insert(ignore_permissions=True)
		add_do_not_contact("Email", ERASED)

		# the row already holding her address does not stop other edits
		deal.reload()
		deal.organization = "Blocking Test Org 2"
		deal.save(ignore_permissions=True)

		# a new row with it does
		deal.reload()
		deal.append("contacts", {"contact": other.name, "email": "MARISOL@x.net"})
		with self.assertRaisesRegex(frappe.ValidationError, MESSAGE):
			deal.save(ignore_permissions=True)

	def test_contact_blocked(self):
		add_do_not_contact("Email", ERASED)
		add_do_not_contact("Phone", "+19165550100")

		with self.assertRaisesRegex(frappe.ValidationError, MESSAGE):
			make_contact("Marisol@x.net")
		with self.assertRaisesRegex(frappe.ValidationError, MESSAGE):
			make_contact("someone.else@x.net", phone="916.555.0100")

	def test_existing_contact_saves_if_unchanged_and_blocks_new_email(self):
		contact = make_contact(ERASED, "+19165550100")
		add_do_not_contact("Email", ERASED)
		add_do_not_contact("Phone", "+19165550100")

		contact.reload()
		contact.first_name = "Renamed"
		contact.save(ignore_permissions=True)

		contact.reload()
		contact.append("email_ids", {"email_id": "marisol@x.net"})
		with self.assertRaisesRegex(frappe.ValidationError, MESSAGE):
			contact.save(ignore_permissions=True)

	def test_facebook_sync_path_blocked(self):
		add_do_not_contact("Email", ERASED)
		lead = {
			"id": "blocking-fb-1",
			"field_data": [
				{"name": "full_name", "values": ["Marisol Vega"]},
				{"name": "email", "values": ["MARISOL@x.net"]},
			],
		}
		source = FacebookSyncSource("token", "blocking-form", "blocking-source")
		mapping = {"full_name": "first_name", "email": "email"}
		with (
			patch.object(FacebookSyncSource, "get_form_questions_mapping", return_value=mapping),
			patch.object(FacebookSyncSource, "create_failure_log") as failure_log,
		):
			source.sync_single_lead(lead)

		self.assertFalse(frappe.db.exists("CRM Lead", {"facebook_lead_id": "blocking-fb-1"}))
		self.assertFalse(frappe.db.exists("CRM Lead", {"email": ERASED}))
		# skipped quietly: nothing is logged, since the log would hold her details
		failure_log.assert_not_called()
		self.assertFalse(frappe.db.exists("Failed Lead Sync Log", {"source": "blocking-source"}))

	# -- inbound email -----------------------------------------------------------------------

	def test_inbound_email_open_request_attached(self):
		request = make_request(identifiers=[{"kind": "Email", "value": "Marisol@X.net"}])
		email = make_email('"Marisol Vega" <marisol@x.net>').insert(ignore_permissions=True)

		email.reload()
		self.assertEqual(
			(email.reference_doctype, email.reference_name), ("CRM Erasure Request", request.name)
		)
		self.assertFalse(frappe.db.exists("CRM Lead", {"email": ERASED}))
		self.assertFalse(frappe.db.exists("CRM Notification", {"reference_name": email.name}))

	def test_excluded_identifier_is_not_matched(self):
		make_request(identifiers=[{"kind": "Email", "value": "office@x.net", "excluded": 1}])
		email = make_email("office@x.net").insert(ignore_permissions=True)

		email.reload()
		self.assertFalse(email.reference_doctype)

	def test_inbound_email_after_close_notifies_compliance_no_lead(self):
		request = make_request(identifiers=[{"kind": "Email", "value": ERASED}])
		add_do_not_contact("Email", ERASED)
		request.db_set("status", "Closed")

		email = make_email("Marisol@x.net").insert(ignore_permissions=True)

		email.reload()
		self.assertFalse(email.reference_doctype)
		self.assertFalse(email.reference_name)
		notifications = frappe.get_all(
			"CRM Notification",
			filters={
				"to_user": COMPLIANCE_USER,
				"reference_doctype": "Communication",
				"reference_name": email.name,
			},
			fields=["notification_text", "message"],
		)
		self.assertEqual(len(notifications), 1)
		self.assertEqual(notifications[0].notification_text, "Email received from an erased person")
		self.assertNotIn("marisol", (notifications[0].message or "").lower())

		# the lead-from-email path refuses her too
		email.email_account = "Blocking Account"
		real_get_value = frappe.db.get_value

		def get_value(doctype, *args, **kwargs):
			if doctype == "Email Account":
				return 1
			return real_get_value(doctype, *args, **kwargs)

		with patch.object(frappe.db, "get_value", side_effect=get_value):
			create_lead_from_incoming_email(email)
		self.assertFalse(frappe.db.exists("CRM Lead", {"email": ERASED}))

	def test_unrelated_sender_is_untouched(self):
		make_request(identifiers=[{"kind": "Email", "value": ERASED}])
		add_do_not_contact("Email", ERASED)

		email = make_email("bob@x.net").insert(ignore_permissions=True)

		email.reload()
		self.assertFalse(email.reference_doctype)
		self.assertFalse(frappe.db.exists("CRM Notification", {"reference_name": email.name}))

	def test_failing_routing_does_not_reject_the_email(self):
		make_request(identifiers=[{"kind": "Email", "value": ERASED}])
		add_do_not_contact("Email", ERASED)
		frappe.db.set_value("CRM Erasure Request", {"status": ["!=", "Closed"]}, "status", "Closed")

		with patch("crm.privacy.inbound.notify", side_effect=Exception("mail down")):
			email = make_email(ERASED).insert(ignore_permissions=True)
		self.assertTrue(frappe.db.exists("Communication", email.name))

		with patch("crm.privacy.identifiers.scramble", side_effect=Exception("no hash secret")):
			email = make_email("bob@x.net").insert(ignore_permissions=True)
		self.assertTrue(frappe.db.exists("Communication", email.name))

	def test_failing_sender_check_does_not_stop_lead_creation_path(self):
		email = make_email("fresh.sender@x.net", email_account="Blocking Account").insert(
			ignore_permissions=True
		)
		real_get_value = frappe.db.get_value

		def get_value(doctype, *args, **kwargs):
			if doctype == "Email Account":
				return 1
			return real_get_value(doctype, *args, **kwargs)

		with (
			patch.object(frappe.db, "get_value", side_effect=get_value),
			patch("crm.privacy.inbound.is_erased_sender", side_effect=Exception("boom")),
		):
			create_lead_from_incoming_email(email)  # must not raise

		self.assertTrue(frappe.db.exists("CRM Lead", {"email": "fresh.sender@x.net"}))

	# -- inbound mail through Frappe's InboundMail (Email Account append_to CRM Lead) --------

	def make_inbox(self):
		account = frappe.get_doc(
			{
				"doctype": "Email Account",
				"email_account_name": "Privacy Inbox Test",
				"email_id": "privacy-inbox@example.com",
				"enable_incoming": 1,
				"use_imap": 1,
				"imap_folder": [{"folder_name": "INBOX", "append_to": "CRM Lead"}],
			}
		)
		account.flags.ignore_mandatory = True
		account.flags.ignore_validate = True
		return account.insert(ignore_permissions=True)

	def receive(self, account, message_id, sender="Marisol Vega <Marisol@X.net>"):
		"""Run the account's real receive loop over one raw RFC822 message. Its commits are
		held back (the test rolls back); a rollback would mean the mail failed."""
		from frappe.email.receive import InboundMail

		raw = (
			f"Message-ID: <{message_id}@example.com>\r\n"
			f"From: {sender}\r\n"
			"To: privacy-inbox@example.com\r\n"
			"Subject: Please delete my data\r\n"
			"Date: Thu, 05 Nov 2026 10:00:00 +0000\r\n"
			"MIME-Version: 1.0\r\n"
			"Content-Type: text/plain; charset=utf-8\r\n"
			"\r\n"
			"Please erase everything you hold about me.\r\n"
		)
		mail = InboundMail(raw, account, uid="1", seen_status=None, append_to="CRM Lead")
		with (
			patch.object(type(account), "get_inbound_mails", return_value=[mail]),
			patch.object(frappe.db, "commit"),
			patch.object(frappe.db, "rollback") as rollback,
			patch("frappe.core.doctype.communication.communication.Communication.send_email"),
		):
			account.receive()
		rollback.assert_not_called()
		return frappe.db.get_value(
			"Communication",
			{"message_id": ["like", f"%{message_id}%"]},
			["name", "reference_doctype", "reference_name"],
			as_dict=True,
		)

	def assert_imported_without_lead(self, email):
		self.assertTrue(email, "the mail was not imported")
		self.assertFalse(frappe.db.exists("CRM Lead", {"email": ["like", "%marisol@x.net%"]}))
		self.assertFalse(frappe.db.exists("Unhandled Email", {"email_account": "Privacy Inbox Test"}))

	def test_inbound_mail_open_request_sender_imported_without_lead(self):
		account = self.make_inbox()
		request = make_request(identifiers=[{"kind": "Email", "value": ERASED}])

		email = self.receive(account, "privacy-inbound-open")

		self.assert_imported_without_lead(email)
		self.assertEqual(
			(email.reference_doctype, email.reference_name), ("CRM Erasure Request", request.name)
		)

	def test_inbound_mail_do_not_contact_sender_imported_without_lead(self):
		account = self.make_inbox()
		add_do_not_contact("Email", ERASED)

		email = self.receive(account, "privacy-inbound-erased")

		self.assert_imported_without_lead(email)
		self.assertFalse(email.reference_doctype)
		self.assertTrue(
			frappe.db.exists(
				"CRM Notification",
				{
					"to_user": COMPLIANCE_USER,
					"reference_doctype": "Communication",
					"reference_name": email.name,
				},
			)
		)

	def test_inbound_mail_other_sender_still_creates_a_lead(self):
		account = self.make_inbox()
		add_do_not_contact("Email", ERASED)

		email = self.receive(account, "privacy-inbound-other", sender="Bob Stone <bob.stone@x.net>")

		self.assertEqual(email.reference_doctype, "CRM Lead")
		self.assertEqual(frappe.db.get_value("CRM Lead", email.reference_name, "email"), "bob.stone@x.net")

	# -- WhatsApp ----------------------------------------------------------------------------

	def test_whatsapp_message_from_erased_number_saved_without_lead_and_compliance_told(self):
		add_do_not_contact("Phone", "+19165550100")
		message = frappe._dict(
			direction="Incoming",
			whatsapp_account="Blocking WA",
			to="Blocking Profile",
			name="WAM-BLOCKING-1",
			reference_doctype=None,
			reference_docname=None,
			flags=frappe._dict(),
		)

		def create_lead(doc, action):
			return make_lead(first_name="W", mobile_no="(916) 555-0100").name

		with (
			patch("crm.api.whatsapp._get_phone_number_from_profile", return_value="(916) 555-0100"),
			patch("crm.api.whatsapp._link_profile_to_crm_entities"),
			patch("crm.api.whatsapp.find_contact_lead_or_deal_from_number", return_value=(None, None)),
			patch("crm.api.whatsapp._lead_append_action", return_value=frappe._dict()),
			patch("crm.api.whatsapp._create_lead", side_effect=create_lead),
		):
			validate_whatsapp_message(message, None)  # must not raise

		self.assertFalse(message.reference_doctype)
		self.assertFalse(message.reference_docname)
		self.assertFalse(frappe.db.exists("CRM Lead", {"mobile_no": "(916) 555-0100"}))

		with patch("crm.privacy.inbound.notify") as notify:
			on_whatsapp_insert(message, None)
		notify.assert_called_once()
		args, kwargs = notify.call_args
		self.assertEqual(args[1], "WhatsApp message received from an erased person")
		self.assertEqual(
			(kwargs["reference_doctype"], kwargs["reference_name"]), ("WA Message", message.name)
		)
		self.assertNotIn("555", args[2])

	def test_whatsapp_message_without_erased_flag_notifies_nobody(self):
		message = frappe._dict(name="WAM-BLOCKING-2", flags=frappe._dict())
		with patch("crm.privacy.inbound.notify") as notify:
			on_whatsapp_insert(message, None)
		notify.assert_not_called()
