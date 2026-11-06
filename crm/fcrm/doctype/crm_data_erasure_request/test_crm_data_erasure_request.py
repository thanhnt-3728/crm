# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import datetime

import frappe
from frappe.tests import IntegrationTestCase

from crm.fcrm.doctype.crm_data_erasure_request.crm_data_erasure_request import (
	PRIVACY_ROLE,
	add_business_days,
)
from crm.fcrm.doctype.crm_data_erasure_request.erasure import ERASED_EMAIL, scrub_addresses
from crm.permissions.test_org_hierarchy import make_user

REP = "rep-der-7731@example.com"
PRIVACY = "privacy-der-7731@example.com"
PRIVACY_2 = "privacy2-der-7731@example.com"
MANAGER = "manager-der-7731@example.com"
EMAIL = "marisol-der-7731@example.net"
PHONE = "+1 916 555 0142"


class TestBusinessDays(IntegrationTestCase):
	def test_ten_business_days_skip_weekends(self):
		# Received Mon 26 Oct 2026, acknowledge by Mon 9 Nov 2026.
		self.assertEqual(add_business_days("2026-10-26", 10), datetime.date(2026, 11, 9))

	def test_starting_on_a_friday(self):
		self.assertEqual(add_business_days("2026-10-30", 1), datetime.date(2026, 11, 2))


class TestScrubAddresses(IntegrationTestCase):
	def test_replaces_only_the_persons_address(self):
		value = "Marisol Vega <Marisol-DER-7731@example.net>, other@example.com"
		self.assertEqual(scrub_addresses(value, {EMAIL}), f"{ERASED_EMAIL}, other@example.com")

	def test_leaves_empty_values(self):
		self.assertIsNone(scrub_addresses(None, {EMAIL}))


class TestCRMDataErasureRequest(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_user(REP, roles=["Sales User"])
		make_user(MANAGER, roles=["Sales Manager"])
		make_user(PRIVACY, roles=[PRIVACY_ROLE])
		make_user(PRIVACY_2, roles=[PRIVACY_ROLE])

	def setUp(self):
		frappe.db.savepoint("test_data_erasure")
		frappe.set_user("Administrator")
		self.org = make_org("Sierra Foothills Dental DER")
		self.lead = make_lead(self.org)
		self.contact = make_contact()
		self.other_contact = make_contact("Jordan", "jordan-der-7731@example.com")
		self.won = make_deal(self.lead.name, self.org, [self.contact.name], status="Won", value=12000)
		self.open = make_deal(
			self.lead.name, self.org, [self.contact.name, self.other_contact.name], status="Negotiation", value=8000
		)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback(save_point="test_data_erasure")

	def log_request(self, user=REP, **kwargs):
		frappe.set_user(user)
		doc = frappe.get_doc(
			{"doctype": "CRM Data Erasure Request", "lead": self.lead.name, "received_on": "2026-10-26", **kwargs}
		).insert()
		frappe.set_user("Administrator")
		return doc

	# Logging ----------------------------------------------------------------------

	def test_logging_sets_deadlines_and_requester(self):
		request = self.log_request()

		self.assertEqual(request.status, "Pending Approval")
		self.assertEqual(request.requested_by, REP)
		self.assertEqual(str(request.acknowledge_by), "2026-11-09")
		self.assertEqual(str(request.respond_by), "2026-12-10")
		self.assertEqual(request.subject_email, EMAIL)

	def test_only_one_open_request_per_lead(self):
		self.log_request()
		with self.assertRaises(frappe.ValidationError):
			self.log_request()

	def test_status_cannot_be_edited_directly(self):
		request = self.log_request()
		frappe.set_user(PRIVACY)
		request.reload()
		request.status = "Completed"
		with self.assertRaises(frappe.ValidationError):
			request.save()

	# Separation of duties ---------------------------------------------------------

	def test_the_rep_who_logged_it_cannot_approve(self):
		request = self.log_request()
		frappe.set_user(REP)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc("CRM Data Erasure Request", request.name).approve_and_erase()

	def test_sales_managers_cannot_approve(self):
		request = self.log_request()
		frappe.set_user(MANAGER)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc("CRM Data Erasure Request", request.name).approve_and_erase()

	def test_privacy_officer_cannot_approve_their_own_request(self):
		request = self.log_request()
		request.db_set("requested_by", PRIVACY)
		frappe.set_user(PRIVACY)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc("CRM Data Erasure Request", request.name).approve_and_erase()

	def test_reject_needs_a_reason_and_closes_the_request(self):
		request = self.log_request()
		frappe.set_user(PRIVACY)
		doc = frappe.get_doc("CRM Data Erasure Request", request.name)
		with self.assertRaises(frappe.ValidationError):
			doc.reject("")
		doc.reject("Not a California resident")

		doc.reload()
		self.assertEqual(doc.status, "Rejected")
		self.assertEqual(doc.decided_by, PRIVACY)
		with self.assertRaises(frappe.ValidationError):
			doc.approve_and_erase()

	# Erasure ----------------------------------------------------------------------

	def test_erasure_end_to_end(self):
		note_on_shared_deal = add_note("CRM Deal", self.open.name, "Call Marisol about pricing")
		comment_on_lead = add_comment("CRM Lead", self.lead.name, "Marisol prefers mornings")
		email = add_email("CRM Deal", self.won.name, sender=EMAIL, recipients=REP)
		deal_values = frappe.get_all(
			"CRM Deal",
			filters={"name": ("in", [self.won.name, self.open.name])},
			fields=["name", "status", "deal_value", "expected_deal_value", "organization", "closed_date"],
			order_by="name",
		)
		lead_counts = frappe.db.count("CRM Lead"), frappe.db.count("CRM Deal")

		request = self.log_request()
		frappe.set_user(PRIVACY)
		frappe.get_doc("CRM Data Erasure Request", request.name).approve_and_erase()
		frappe.set_user("Administrator")
		marker = f"Content erased {request.name}"

		# Reports don't move: same records, values, statuses, organizations.
		self.assertEqual((frappe.db.count("CRM Lead"), frappe.db.count("CRM Deal")), lead_counts)
		self.assertEqual(
			frappe.get_all(
				"CRM Deal",
				filters={"name": ("in", [self.won.name, self.open.name])},
				fields=["name", "status", "deal_value", "expected_deal_value", "organization", "closed_date"],
				order_by="name",
			),
			deal_values,
		)
		self.assertTrue(frappe.db.exists("CRM Organization", self.org))

		# The lead is de-identified but keeps its company details.
		lead = frappe.db.get_value(
			"CRM Lead", self.lead.name, ["lead_name", "email", "mobile_no", "last_name", "organization"], as_dict=True
		)
		self.assertEqual(lead.lead_name, marker)
		self.assertFalse(lead.email or lead.mobile_no or lead.last_name)
		self.assertEqual(lead.organization, self.org)

		# The contact is gone, with no recoverable copy.
		self.assertFalse(frappe.db.exists("Contact", self.contact.name))
		self.assertFalse(
			frappe.db.exists("Deleted Document", {"deleted_doctype": "Contact", "deleted_name": self.contact.name})
		)

		# The shared deal keeps the other contact, now primary.
		open_deal = frappe.get_doc("CRM Deal", self.open.name)
		self.assertEqual([c.contact for c in open_deal.contacts], [self.other_contact.name])
		self.assertEqual(open_deal.contact, self.other_contact.name)
		self.assertEqual(open_deal.email, "jordan-der-7731@example.com")
		self.assertFalse(frappe.get_doc("CRM Deal", self.won.name).contacts)

		# Activity records stay, their text does not.
		self.assertEqual(frappe.db.get_value("FCRM Note", note_on_shared_deal, "content"), marker)
		self.assertEqual(frappe.db.get_value("Comment", comment_on_lead, "content"), marker)
		comm = frappe.db.get_value("Communication", email, ["subject", "content", "sender"], as_dict=True)
		self.assertEqual((comm.subject, comm.content, comm.sender), (marker, marker, ERASED_EMAIL))

		# No history keeps the old values.
		self.assertFalse(frappe.db.exists("Version", {"ref_doctype": "CRM Lead", "docname": self.lead.name}))

		request.reload()
		self.assertEqual(request.status, "Completed")
		self.assertEqual(request.decided_by, PRIVACY)
		self.assertIsNone(request.contact)

		# The same lead can't be erased twice.
		with self.assertRaises(frappe.ValidationError):
			self.log_request()

	def test_preview_lists_what_will_be_touched(self):
		add_note("CRM Lead", self.lead.name, "First call")
		request = self.log_request()
		frappe.set_user(PRIVACY)

		preview = frappe.get_doc("CRM Data Erasure Request", request.name).get_preview()

		self.assertEqual(preview["leads"], [self.lead.name])
		self.assertEqual(set(preview["deals"]), {self.won.name, self.open.name})
		self.assertEqual(preview["contacts"], [self.contact.name])
		self.assertEqual(preview["counts"]["FCRM Note"], 1)


def make_org(name):
	if not frappe.db.exists("CRM Organization", name):
		frappe.get_doc({"doctype": "CRM Organization", "organization_name": name}).insert(ignore_permissions=True)
	return name


def make_lead(org):
	return frappe.get_doc(
		{
			"doctype": "CRM Lead",
			"first_name": "Marisol",
			"last_name": "Vega",
			"email": EMAIL,
			"mobile_no": PHONE,
			"organization": org,
			"lead_owner": REP,
		}
	).insert(ignore_permissions=True)


def make_contact(first_name="Marisol", email=EMAIL):
	return frappe.get_doc(
		{
			"doctype": "Contact",
			"first_name": first_name,
			"last_name": "Vega" if email == EMAIL else "Lee",
			"email_ids": [{"email_id": email, "is_primary": 1}],
			"phone_nos": [{"phone": PHONE, "is_primary_mobile_no": 1}] if email == EMAIL else [],
		}
	).insert(ignore_permissions=True)


def make_deal(lead, org, contacts, status, value):
	doc = frappe.get_doc(
		{
			"doctype": "CRM Deal",
			"lead": lead,
			"organization": org,
			"deal_owner": REP,
			"status": status,
			"deal_value": value,
			"first_name": "Marisol",
			"last_name": "Vega",
			"contacts": [{"contact": c} for c in contacts],
		}
	)
	doc.flags.ignore_mandatory = True
	doc.flags.ignore_links = True
	return doc.insert(ignore_permissions=True)


def add_note(doctype, name, content):
	return (
		frappe.get_doc(
			{
				"doctype": "FCRM Note",
				"title": content,
				"content": content,
				"reference_doctype": doctype,
				"reference_docname": name,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def add_comment(doctype, name, content):
	return (
		frappe.get_doc(
			{
				"doctype": "Comment",
				"comment_type": "Comment",
				"content": content,
				"reference_doctype": doctype,
				"reference_name": name,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def add_email(doctype, name, sender, recipients):
	return (
		frappe.get_doc(
			{
				"doctype": "Communication",
				"communication_type": "Communication",
				"communication_medium": "Email",
				"sent_or_received": "Received",
				"subject": "Renewal for Marisol",
				"content": "Hi Tyler, ...",
				"sender": sender,
				"recipients": recipients,
				"reference_doctype": doctype,
				"reference_name": name,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)
