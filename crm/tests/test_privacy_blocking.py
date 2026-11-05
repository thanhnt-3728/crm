# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from crm.fcrm.doctype.crm_erasure_request.test_crm_erasure_request import make_request, make_user
from crm.lead_syncing.doctype.lead_sync_source.facebook import FacebookSyncSource
from crm.privacy.identifiers import add_do_not_contact
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
		# it is logged as a failure, with the reason in the traceback
		self.assertTrue(failure_log.called)
		self.assertIn(MESSAGE, failure_log.call_args.kwargs["traceback"])

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
