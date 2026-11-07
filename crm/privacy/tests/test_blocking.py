# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The server-side block on new and changed emails and phones (design 5.9)."""

import frappe
from frappe.tests import IntegrationTestCase

from crm.privacy.do_not_contact import ErasedPersonBlockedError
from crm.privacy.install import setup
from crm.privacy.tests.make_test_user import block, make_contact, make_deal, make_lead

EMAIL, PHONE = "marisol.vega@example.net", "+15305550123"
LEAD, DEAL, CONTACT = "CRM Lead", "CRM Deal", "Contact"


class BlockingTestCase(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		setup()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def block_her(self):
		block(("email", EMAIL), ("phone", PHONE))

	def assertBlocked(self, function, *args, **kwargs):
		with self.assertRaises(ErasedPersonBlockedError) as caught:
			function(*args, **kwargs)
		message = str(caught.exception).lower()
		self.assertIn("asked to be erased", message)
		for echoed in ("marisol", "example.net", "5305550123", "pdr"):
			self.assertNotIn(echoed, message)
		del frappe.local.message_log[:]


class TestBlockNewRecords(BlockingTestCase):
	def test_a_lead_with_her_email_in_another_case_is_refused(self):
		self.block_her()

		self.assertBlocked(make_lead, email=" Marisol.Vega@Example.net ")

		self.assertFalse(frappe.db.exists(LEAD, {"first_name": "Marisol", "last_name": "Vega"}))

	def test_a_lead_with_her_phone_in_any_format_is_refused(self):
		self.block_her()

		for field in ("mobile_no", "phone"):
			self.assertBlocked(make_lead, **{field: "(530) 555-0123"})

	def test_a_lead_with_other_details_is_created(self):
		self.block_her()

		name = make_lead(email="someone.else@example.net", mobile_no="+15305550999")

		self.assertTrue(frappe.db.exists(LEAD, name))

	def test_the_message_is_the_same_for_every_path(self):
		self.block_her()
		with self.assertRaises(ErasedPersonBlockedError) as caught:
			make_lead(email=EMAIL)
		self.assertEqual(
			str(caught.exception),
			"This person asked to be erased. Their email or phone can't be added to the CRM.",
		)

	def test_a_new_contact_with_her_email_or_phone_row_is_refused(self):
		self.block_her()

		self.assertBlocked(make_contact, "Mari", emails=[EMAIL.upper()])
		self.assertBlocked(make_contact, "Mari", phones=["530 555 0123"])
		self.assertFalse(frappe.db.exists(CONTACT, {"first_name": "Mari"}))

	def test_a_deal_whose_contact_row_carries_her_phone_is_refused(self):
		contact = make_contact("Shared", emails=["shared@example.net"], phones=["+1 530-555-0123"])
		self.block_her()

		self.assertBlocked(make_deal, [contact])

	def test_a_deal_whose_contact_row_carries_her_email_is_refused(self):
		contact = make_contact("Shared", emails=[EMAIL])
		self.block_her()

		self.assertBlocked(make_deal, [contact])

	def test_a_deal_cannot_keep_her_email_in_its_own_field(self):
		self.block_her()

		deal = make_deal(email=EMAIL, mobile_no=PHONE)  # the deal's own fields mirror its primary contact

		self.assertFalse(any(frappe.db.get_value(DEAL, deal, ["email", "mobile_no"])))

	def test_the_erasure_flag_skips_the_check(self):
		self.block_her()
		frappe.flags.in_erasure = True
		try:
			name = make_lead(email=EMAIL)
		finally:
			frappe.flags.in_erasure = False

		self.assertTrue(frappe.db.exists(LEAD, name))


class TestBlockChanges(BlockingTestCase):
	def test_an_existing_lead_saves_when_its_blocked_phone_is_not_touched(self):
		lead = make_lead(mobile_no=PHONE)
		self.block_her()

		doc = frappe.get_doc(LEAD, lead)
		doc.company_description = "Unrelated edit"
		doc.save()

		self.assertEqual(frappe.db.get_value(LEAD, lead, "company_description"), "Unrelated edit")

	def test_changing_a_lead_to_her_phone_or_email_is_refused(self):
		lead = make_lead(mobile_no="+15305550999", email="other@example.net")
		self.block_her()

		doc = frappe.get_doc(LEAD, lead)
		doc.mobile_no = "(530) 555-0123"
		self.assertBlocked(doc.save)
		doc = frappe.get_doc(LEAD, lead)
		doc.email = EMAIL
		self.assertBlocked(doc.save)

	def test_filling_an_empty_field_with_her_value_is_refused(self):
		lead = make_lead(email="other@example.net")
		self.block_her()

		doc = frappe.get_doc(LEAD, lead)
		doc.phone = PHONE
		self.assertBlocked(doc.save)

	def test_adding_her_email_or_phone_row_to_a_contact_is_refused(self):
		contact = make_contact("Other", emails=["other@example.net"], phones=["+15305550999"])
		self.block_her()

		doc = frappe.get_doc(CONTACT, contact)
		doc.append("email_ids", {"email_id": " Marisol.Vega@Example.net"})
		self.assertBlocked(doc.save)
		doc = frappe.get_doc(CONTACT, contact)
		doc.append("phone_nos", {"phone": "(530) 555-0123"})
		self.assertBlocked(doc.save)

	def test_a_contact_that_already_holds_her_email_saves_when_it_is_not_touched(self):
		contact = make_contact("Shared", emails=[EMAIL, "other@example.net"])
		self.block_her()

		doc = frappe.get_doc(CONTACT, contact)
		doc.append("email_ids", {"email_id": "third@example.net"})
		doc.designation = "Buyer"
		doc.save()

		self.assertEqual(frappe.db.get_value(CONTACT, contact, "designation"), "Buyer")

	def test_a_deal_that_lists_her_value_saves_when_the_contacts_are_not_touched(self):
		contact = make_contact("Shared", phones=[PHONE])
		deal = make_deal([contact])
		self.block_her()

		doc = frappe.get_doc(DEAL, deal)
		doc.status = "Negotiation"
		doc.save()

		self.assertEqual(frappe.db.get_value(DEAL, deal, "status"), "Negotiation")

	def test_adding_a_contact_row_that_carries_her_value_to_a_deal_is_refused(self):
		clean = make_contact("Clean", emails=["clean@example.net"])
		shared = make_contact("Shared", phones=[PHONE])
		deal = make_deal([clean])
		self.block_her()

		doc = frappe.get_doc(DEAL, deal)
		doc.append("contacts", {"contact": shared})
		self.assertBlocked(doc.save)
