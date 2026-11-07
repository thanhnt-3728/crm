# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Field by field: a blocked value moved into another field is a change (M2); phone formats (L2)."""

import frappe

from crm.privacy.identifiers import normalize_identifier
from crm.privacy.tests.make_test_user import block, make_contact, make_lead
from crm.privacy.tests.test_blocking import CONTACT, LEAD, PHONE, BlockingTestCase


class TestScalarFields(BlockingTestCase):
	def test_moving_a_saved_blocked_value_into_another_field_is_refused(self):
		lead = make_lead(phone=PHONE)
		self.block_her()

		doc = frappe.get_doc(LEAD, lead)
		doc.mobile_no = PHONE
		self.assertBlocked(doc.save)

	def test_the_field_that_already_holds_it_stays_savable(self):
		lead = make_lead(phone=PHONE, mobile_no="+15305550999")
		self.block_her()

		doc = frappe.get_doc(LEAD, lead)
		doc.mobile_no = "+15305550998"  # another field changes, the blocked one does not
		doc.save()

		self.assertEqual(frappe.db.get_value(LEAD, lead, "phone"), PHONE)

	def test_a_value_swapped_between_two_rows_of_one_table_is_not_new(self):
		contact = make_contact("Shared", phones=[PHONE, "+15305550999"])
		self.block_her()

		doc = frappe.get_doc(CONTACT, contact)
		doc.phone_nos[0].phone, doc.phone_nos[1].phone = doc.phone_nos[1].phone, doc.phone_nos[0].phone
		doc.save()

		phones = frappe.get_all("Contact Phone", {"parent": contact}, pluck="phone")
		self.assertEqual(sorted(phones), sorted([PHONE, "+15305550999"]))

	def test_a_row_edited_to_a_blocked_value_is_refused(self):
		contact = make_contact("Other", phones=["+15305550999"])
		self.block_her()

		doc = frappe.get_doc(CONTACT, contact)
		doc.phone_nos[0].phone = "(530) 555-0123"
		self.assertBlocked(doc.save)


class TestPhoneFormats(BlockingTestCase):
	def test_an_international_00_prefix_is_a_plus(self):
		for typed in ("001 415 555 0199", "0014155550199", "+1 (415) 555-0199", "1-415-555-0199", "415.555.0199"):
			self.assertEqual(normalize_identifier("phone", typed), "+14155550199", typed)

	def test_a_phone_typed_with_00_is_blocked(self):
		block(("phone", "+1 415 555 0199"))

		self.assertBlocked(make_lead, mobile_no="001 415 555 0199")
