# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The block on the paths that create records on their own: import, WhatsApp, Facebook, call log (design 5.9)."""

import frappe

from crm.api.whatsapp import validate as validate_whatsapp_message
from crm.fcrm.doctype.crm_call_log.crm_call_log import create_lead_from_call_log
from crm.fcrm.doctype.crm_call_log.test_crm_call_log import create_test_call_log
from crm.privacy.tests.automatic_path_fixtures import facebook_source, incoming_whatsapp_message, meta_lead
from crm.privacy.tests.make_test_user import make_lead
from crm.privacy.tests.test_blocking import EMAIL, LEAD, PHONE, BlockingTestCase


class TestImportPath(BlockingTestCase):
	"""Data Import builds `frappe.new_doc(...)`, updates it from the row and calls `insert()`."""

	def import_row(self, doctype: str, **row):
		doc = frappe.new_doc(doctype)
		doc.update(row)
		doc.flags.updater_reference = {"doctype": "Data Import", "docname": "DI-1", "label": "via Data Import"}
		frappe.flags.in_import = True
		try:
			return doc.insert()
		finally:
			frappe.flags.in_import = False

	def test_a_lead_row_with_her_email_fails_with_the_message(self):
		self.block_her()

		self.assertBlocked(self.import_row, LEAD, first_name="Marisol", email=EMAIL)

	def test_a_contact_row_with_her_phone_fails_with_the_message(self):
		self.block_her()

		self.assertBlocked(
			self.import_row, "Contact", first_name="Mari", phone_nos=[{"phone": "530.555.0123"}]
		)

	def test_a_row_with_other_details_is_imported(self):
		self.block_her()

		lead = self.import_row(LEAD, first_name="Someone", email="someone@example.net")

		self.assertTrue(frappe.db.exists(LEAD, lead.name))


class TestCallLogPath(BlockingTestCase):
	def test_creating_a_lead_from_her_number_is_refused_and_the_call_stays_unlinked(self):
		call = create_test_call_log(type="Incoming", from_number="(530) 555-0123")
		self.block_her()

		self.assertBlocked(create_lead_from_call_log, call_log=frappe.as_json({"name": call.name}))

		call.reload()
		self.assertFalse(call.has_link(LEAD, call.name))
		self.assertFalse(frappe.db.exists(LEAD, {"mobile_no": "(530) 555-0123"}))

	def test_another_number_still_becomes_a_lead(self):
		call = create_test_call_log(type="Incoming", from_number="+15305550999")
		self.block_her()

		name = create_lead_from_call_log(call_log=frappe.as_json({"name": call.name}))

		self.assertTrue(frappe.db.exists(LEAD, name))


class TestWhatsAppPath(BlockingTestCase):
	def test_a_message_from_her_number_is_saved_without_a_lead(self):
		message = incoming_whatsapp_message(PHONE)
		self.block_her()

		validate_whatsapp_message(message, None)

		self.assertFalse(message.reference_docname)
		self.assertFalse(frappe.db.exists(LEAD, {"mobile_no": PHONE}))
		self.assertEqual(frappe.local.message_log, [])

	def test_a_message_from_a_new_number_still_becomes_a_lead(self):
		message = incoming_whatsapp_message("+15305550999")
		self.block_her()

		validate_whatsapp_message(message, None)

		self.assertEqual(message.reference_doctype, LEAD)
		self.assertTrue(frappe.db.exists(LEAD, message.reference_docname))

	def test_a_message_from_a_number_that_already_has_a_lead_is_linked_to_it(self):
		lead = make_lead(mobile_no=PHONE)
		message = incoming_whatsapp_message(PHONE)
		self.block_her()

		validate_whatsapp_message(message, None)

		self.assertEqual(message.reference_docname, lead)


class TestFacebookPath(BlockingTestCase):
	def test_her_lead_is_skipped_without_a_failure_log_or_a_stored_payload(self):
		source = facebook_source()
		self.block_her()
		logs_before = frappe.db.count("Failed Lead Sync Log")

		result = source.sync_single_lead(meta_lead("fb-1", " Marisol.Vega@Example.net"))

		self.assertIsNone(result)
		self.assertFalse(frappe.db.exists(LEAD, {"facebook_lead_id": "fb-1"}))
		self.assertEqual(frappe.db.count("Failed Lead Sync Log"), logs_before)
		self.assertEqual(source.skipped, 1)
		self.assertEqual(frappe.local.message_log, [])

	def test_another_lead_in_the_same_batch_is_imported(self):
		source = facebook_source()
		self.block_her()

		source.sync_single_lead(meta_lead("fb-1", EMAIL))
		source.sync_single_lead(meta_lead("fb-2", "someone.else@example.net"))

		self.assertFalse(frappe.db.exists(LEAD, {"facebook_lead_id": "fb-1"}))
		self.assertTrue(frappe.db.exists(LEAD, {"facebook_lead_id": "fb-2"}))
		self.assertEqual(source.skipped, 1)
