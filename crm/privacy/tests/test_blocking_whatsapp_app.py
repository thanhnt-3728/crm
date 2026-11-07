# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The whatsapp app's own path for an incoming message: insert, submit, then `process_append_actions` (M3).

The webhook (`whatsapp.webhook`) runs exactly that sequence, and `process_append_actions` tries to create the
lead a second time when the message is still unlinked. This test drives the sequence itself.
"""

import frappe
from whatsapp.whatsapp.doctype.wa_message.wa_message import process_append_actions

from crm.privacy.tests.automatic_path_fixtures import incoming_whatsapp_message
from crm.privacy.tests.make_test_user import RequestTestCase, block, purge_logs_titled
from crm.privacy.tests.test_blocking import PHONE

LEAD = "CRM Lead"
APP_TITLE = "WhatsApp Append Action Failed"


class TestWhatsAppAppPath(RequestTestCase):
	def tearDown(self):
		frappe.db.rollback()
		purge_logs_titled(self._started, APP_TITLE)
		frappe.db.delete("WA Log", {"creation": [">=", self._started]})
		frappe.db.commit()
		super().tearDown()

	def receive(self, number: str):
		"""What the webhook does with an incoming message."""
		message = incoming_whatsapp_message(number)
		message.flags.ignore_permissions = True
		message.insert()
		message.submit()
		process_append_actions(message, trigger_on="Incoming")
		return message

	def logs_since_start(self) -> str:
		rows = frappe.get_all("Error Log", {"creation": [">=", self._started]}, ["method", "error", "reference_name"])
		wa = frappe.get_all("WA Log", {"creation": [">=", self._started]}, ["*"])
		return frappe.as_json({"error_log": rows, "wa_log": wa})

	def test_a_blocked_number_gets_no_lead_and_nothing_reaches_the_webhook(self):
		block(("phone", PHONE))

		message = self.receive(PHONE)  # no exception is the point: the webhook would answer an error

		self.assertTrue(frappe.db.exists("WA Message", message.name))
		self.assertFalse(frappe.db.get_value("WA Message", message.name, "reference_docname"))
		self.assertFalse(frappe.db.exists(LEAD, {"mobile_no": PHONE}))

	def test_the_logs_of_both_attempts_hold_no_personal_data(self):
		block(("phone", PHONE))

		self.receive(PHONE)

		dump = self.logs_since_start()
		for personal in ("5305550123", "Marisol"):
			self.assertNotIn(personal, dump)
		for row in frappe.get_all("Error Log", {"creation": [">=", self._started], "method": APP_TITLE}, ["error"]):
			self.assertEqual(row.error, "ErasedPersonBlockedError")

	def test_another_number_is_unaffected(self):
		block(("phone", PHONE))

		message = self.receive("+15305550999")

		self.assertTrue(frappe.db.get_value("WA Message", message.name, "reference_docname"))
		self.assertTrue(frappe.db.exists(LEAD, {"mobile_no": "+15305550999"}))
