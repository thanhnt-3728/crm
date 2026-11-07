# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The Error Log scrub follows the exception being handled, not a word in the text (L1)."""

import frappe
from frappe.tests import IntegrationTestCase

from crm.privacy.do_not_contact import ErasedPersonBlockedError, PrivacySettingsIncompleteError

TITLE = "Scrub probe"


def blocked(kind=ErasedPersonBlockedError):
	frappe.throw("This person asked to be erased. Their email or phone can't be added to the CRM.", kind)


class TestScrubFollowsTheExceptionChain(IntegrationTestCase):
	def setUp(self):
		self.started = frappe.utils.add_to_date(frappe.utils.now_datetime(), seconds=-1)

	def tearDown(self):
		frappe.db.rollback()
		frappe.db.delete("Error Log", {"method": TITLE, "creation": [">=", self.started]})
		frappe.db.commit()

	def log(self, reference_name="Marisol.Vega"):
		frappe.log_error(TITLE, reference_doctype="Contact", reference_name=reference_name)
		return frappe.get_all(
			"Error Log",
			{"method": TITLE, "creation": [">=", self.started]},
			["error", "reference_name"],
			order_by="creation asc",
		)[-1]

	def test_a_block_error_being_handled_leaves_only_its_class_name(self):
		for kind in (ErasedPersonBlockedError, PrivacySettingsIncompleteError):
			try:
				blocked(kind)
			except kind:
				row = self.log()
			self.assertEqual(row.error, kind.__name__)
			self.assertIsNone(row.reference_name)

	def test_an_unrelated_error_raised_while_handling_one_keeps_its_real_text(self):
		try:
			blocked()
		except ErasedPersonBlockedError:
			try:
				raise KeyError("real bug")
			except KeyError:
				row = self.log()

		self.assertIn("real bug", row.error)
		self.assertNotIn("Traceback", row.error)  # the locals of the frames are gone
		self.assertIsNone(row.reference_name)

	def test_an_unrelated_error_is_left_alone(self):
		try:
			raise KeyError("another bug")
		except KeyError:
			row = self.log("CRM-LEAD-1")

		self.assertIn("Traceback", row.error)
		self.assertEqual(row.reference_name, "CRM-LEAD-1")

	def test_the_class_name_in_a_log_text_alone_is_not_enough(self):
		frappe.log_error(TITLE, "mentions ErasedPersonBlockedError in a note", "Contact", "CRM-LEAD-2")
		(row,) = frappe.get_all(
			"Error Log", {"method": TITLE, "creation": [">=", self.started]}, ["error", "reference_name"]
		)

		self.assertEqual(row.error, "mentions ErasedPersonBlockedError in a note")
		self.assertEqual(row.reference_name, "CRM-LEAD-2")
