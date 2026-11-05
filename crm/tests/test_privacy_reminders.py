from datetime import date
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, add_months, getdate, today

from crm.fcrm.doctype.crm_erasure_request.test_crm_erasure_request import make_request, make_user
from crm.privacy import system_write
from crm.privacy.notify import notify
from crm.privacy.reminders import send_due_reminders
from crm.privacy.retention import purge_expired
from crm.privacy.setup import ensure_privacy_setup

HEAD = "head@example.com"
COMPLIANCE_USERS = ["comp1@example.com", "comp2@example.com"]
SETTINGS = "CRM Privacy Settings"
REQUEST = "CRM Erasure Request"
# One fixed "today" for the whole run; every reminder/purge call is passed it explicitly.
NOW = getdate(today())


def notifications(user, request=None):
	filters = {"type": "Privacy", "to_user": user}
	if request:
		filters.update({"reference_doctype": "CRM Erasure Request", "reference_name": request})
	return frappe.get_all("CRM Notification", filters=filters, pluck="message")


def count(user, request):
	"""Privacy notifications for `user` about one request."""
	return len(notifications(user, request.name))


def close(request, **values):
	"""Put the request in the state close leaves it in."""
	with system_write():
		frappe.db.set_value(
			"CRM Erasure Request",
			request.name,
			{"status": "Closed", "answered_on": NOW, "outcome": "Completed", **values},
		)


class TestPrivacyReminders(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_privacy_setup()
		for email in COMPLIANCE_USERS:
			make_user(email, ["Sales User", "Compliance"])
		make_user(HEAD, ["Sales Manager"])

	def setUp(self):
		frappe.set_user("Administrator")
		# Reminders run over every open request: start each test from none, so nothing left by
		# another test (or by a fixed-date request) can send into this one.
		frappe.db.delete("CRM Notification", {"type": "Privacy"})
		frappe.db.delete(REQUEST)
		frappe.db.delete("CRM Retained Contract")
		frappe.db.set_single_value(SETTINGS, "head_of_compliance", HEAD)

	def tearDown(self):
		frappe.db.set_single_value(SETTINGS, "head_of_compliance", None)
		frappe.flags.privacy_system_write = False

	def test_late_logged_request_sends_each_reminder_once(self):
		r = make_request(received_on=add_days(NOW, -41))
		send_due_reminders(NOW)
		send_due_reminders(NOW)
		self.assertEqual(count(HEAD, r), 1)
		for user in COMPLIANCE_USERS:
			# acknowledgment + day 30
			self.assertEqual(count(user, r), 2)

	def test_ack_reminder_three_business_days_before(self):
		r = make_request(received_on="2026-10-26")
		send_due_reminders(date(2026, 11, 3))
		r.reload()
		self.assertFalse(r.ack_reminder_sent)
		send_due_reminders(date(2026, 11, 4))
		r.reload()
		self.assertTrue(r.ack_reminder_sent)
		self.assertEqual(len(notifications(COMPLIANCE_USERS[0], r.name)), 1)

	def test_ack_ticked_suppresses_reminder(self):
		r = make_request(received_on="2026-10-26", acknowledgment_sent=1)
		send_due_reminders(date(2026, 11, 4))
		r.reload()
		self.assertFalse(r.ack_reminder_sent)
		self.assertEqual(notifications(COMPLIANCE_USERS[0], r.name), [])

	def test_day30_and_day40_fire_on_their_days(self):
		r = make_request(received_on="2026-10-26", acknowledgment_sent=1)
		send_due_reminders(date(2026, 11, 24))  # day 29
		r.reload()
		self.assertFalse(r.day30_reminder_sent)
		send_due_reminders(date(2026, 11, 25))  # day 30
		r.reload()
		self.assertTrue(r.day30_reminder_sent)
		self.assertFalse(r.day40_alert_sent)
		self.assertEqual(notifications(HEAD, r.name), [])
		send_due_reminders(date(2026, 12, 5))  # day 40
		r.reload()
		self.assertTrue(r.day40_alert_sent)
		self.assertEqual(len(notifications(HEAD, r.name)), 1)

	def test_day40_falls_back_to_compliance_when_no_head(self):
		frappe.db.set_single_value(SETTINGS, "head_of_compliance", None)
		r = make_request(received_on=add_days(NOW, -41), acknowledgment_sent=1)
		send_due_reminders(NOW)
		r.reload()
		self.assertTrue(r.day40_alert_sent)
		for user in COMPLIANCE_USERS:
			# day 30 + day 40
			self.assertEqual(count(user, r), 2)
		self.assertEqual(notifications(HEAD, r.name), [])

	def test_message_has_days_left_and_no_requester_details(self):
		r = make_request(
			received_on=add_days(NOW, -30),
			acknowledgment_sent=1,
			requester_names="Marisol Vega",
			original_message="Please erase marisol@x.net, 916-555-0100",
		)
		send_due_reminders(NOW)
		(message,) = notifications(COMPLIANCE_USERS[0], r.name)
		self.assertEqual(message, f"{r.name}: 15 of 45 days left — respond by {r.respond_by}")
		for personal in ("Marisol", "Vega", "marisol@x.net", "555"):
			self.assertNotIn(personal, message)

	def test_closed_request_gets_no_reminders(self):
		r = make_request(received_on=add_days(NOW, -41))
		close(r)
		send_due_reminders(NOW)
		self.assertEqual(
			frappe.db.count("CRM Notification", {"type": "Privacy", "reference_name": r.name}), 0
		)

	def test_purge_after_24_months(self):
		closed = make_request(received_on=add_months(NOW, -26))
		close(closed, answered_on=add_months(NOW, -25), delete_after=add_days(NOW, -1))
		young = make_request(received_on=add_months(NOW, -2))
		close(young, delete_after=add_months(NOW, 22))
		open_request = make_request(received_on=add_months(NOW, -26))
		with system_write():
			frappe.db.set_value("CRM Erasure Request", open_request.name, "delete_after", add_days(NOW, -1))
		due = frappe.get_doc(
			{
				"doctype": "CRM Retained Contract",
				"person_name": "Erased person",
				"contract_reference": "C-1",
				"delete_after": add_days(NOW, -1),
			}
		).insert(ignore_permissions=True)
		later = frappe.get_doc(
			{
				"doctype": "CRM Retained Contract",
				"contract_reference": "C-2",
				"delete_after": add_days(NOW, 30),
			}
		).insert(ignore_permissions=True)
		kept = frappe.get_doc({"doctype": "CRM Retained Contract", "contract_reference": "C-3"}).insert(
			ignore_permissions=True
		)

		purge_expired(NOW)

		self.assertFalse(frappe.db.exists("CRM Erasure Request", closed.name))
		self.assertTrue(frappe.db.exists("CRM Erasure Request", young.name))
		self.assertTrue(frappe.db.exists("CRM Erasure Request", open_request.name))
		self.assertFalse(frappe.db.exists("CRM Retained Contract", due.name))
		self.assertTrue(frappe.db.exists("CRM Retained Contract", later.name))
		self.assertTrue(frappe.db.exists("CRM Retained Contract", kept.name))

	def test_purge_leaves_no_deleted_document_copy(self):
		closed = make_request(received_on=add_months(NOW, -26))
		close(closed, delete_after=add_days(NOW, -1))
		purge_expired(NOW)
		self.assertFalse(
			frappe.db.exists(
				"Deleted Document", {"deleted_doctype": "CRM Erasure Request", "deleted_name": closed.name}
			)
		)

	def test_purge_removes_notifications_about_the_request(self):
		closed = make_request(received_on=add_months(NOW, -26))
		send_due_reminders(NOW)
		self.assertTrue(notifications(COMPLIANCE_USERS[0], closed.name))
		close(closed, delete_after=add_days(NOW, -1))
		purge_expired(NOW)
		self.assertFalse(frappe.db.exists("CRM Erasure Request", closed.name))
		self.assertEqual(notifications(COMPLIANCE_USERS[0], closed.name), [])

	def test_template_exists(self):
		self.assertTrue(frappe.db.exists("Email Template", "Erasure outcome"))

	def test_template_covers_required_sections_and_is_not_overwritten(self):
		template = frappe.get_doc("Email Template", "Erasure outcome")
		for text in ("What we erased", "What we kept and why", "24 months", "other people"):
			self.assertIn(text, template.response)
		template.db_set("subject", "Edited by an admin")
		ensure_privacy_setup()
		self.assertEqual(
			frappe.db.get_value("Email Template", "Erasure outcome", "subject"), "Edited by an admin"
		)

	def test_failing_email_keeps_the_in_app_notifications(self):
		r = make_request(received_on=add_days(NOW, -41))
		with (
			patch("crm.privacy.notify.frappe.sendmail", side_effect=Exception("smtp down")),
			patch("crm.privacy.notify.frappe.log_error") as log_error,
		):
			notify(COMPLIANCE_USERS, "Erasure request test", "Body", request=r.name)
		for user in COMPLIANCE_USERS:
			self.assertEqual(notifications(user, r.name), ["Body"])
		log_error.assert_called_once()
		# A fixed message, nothing from the notification itself.
		self.assertNotIn("Body", str(log_error.call_args))

		# The reminder run still marks what it sent in the app.
		with patch("crm.privacy.notify.frappe.sendmail", side_effect=Exception("smtp down")):
			send_due_reminders(NOW)
		self.assertTrue(frappe.db.get_value(REQUEST, r.name, "day40_alert_sent"))
