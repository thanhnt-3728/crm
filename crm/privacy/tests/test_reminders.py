from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import getdate

from crm.permissions.test_org_hierarchy import make_user
from crm.privacy import reminders
from crm.privacy.reminders import send_reminders
from crm.privacy.tests.factories import make_compliance_user, make_request

DOCTYPE = "CRM Erasure Request"


class TestReminders(IntegrationTestCase):
	def setUp(self):
		self.officer = make_compliance_user()
		self.r = make_request(date_received="2026-10-26")

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def count(self, user):
		return frappe.db.count("CRM Notification", {"to_user": user, "notification_type_doc": self.r.name})

	def flag(self, fieldname):
		return frappe.db.get_value(DOCTYPE, self.r.name, fieldname)

	def test_ack_reminder_due_once(self):
		send_reminders(getdate("2026-11-03"))
		self.assertEqual(self.count(self.officer), 0)
		send_reminders(getdate("2026-11-04"))
		self.assertEqual(self.count(self.officer), 1)
		self.assertTrue(self.flag("ack_reminder_sent"))
		send_reminders(getdate("2026-11-05"))
		self.assertEqual(self.count(self.officer), 1)

	def test_ack_reminder_skipped_when_acknowledged(self):
		frappe.db.set_value(DOCTYPE, self.r.name, "acknowledgment_sent", 1)
		send_reminders(getdate("2026-11-04"))
		self.assertEqual(self.count(self.officer), 0)

	def test_late_logged_request_gets_all_due_reminders(self):
		head = make_user("head@example.com", ["Compliance"]).name
		frappe.db.set_single_value("CRM Privacy Settings", "head_of_compliance", head)
		send_reminders(getdate("2026-12-06"))
		self.assertEqual(self.count(self.officer), 2)  # acknowledgment + day 30
		self.assertEqual(self.count(head), 3)  # also a Compliance user, plus the day-40 alert
		for fieldname in ("ack_reminder_sent", "day30_reminder_sent", "day40_alert_sent"):
			self.assertTrue(self.flag(fieldname), fieldname)

	def test_day40_falls_back_without_head(self):
		frappe.db.set_single_value("CRM Privacy Settings", "head_of_compliance", None)
		frappe.db.set_value(DOCTYPE, self.r.name, {"ack_reminder_sent": 1, "day30_reminder_sent": 1})
		send_reminders(getdate("2026-12-05"))
		self.assertEqual(self.count(self.officer), 1)

	def test_day40_falls_back_when_head_disabled(self):
		head = make_user("head@example.com", ["Compliance"]).name
		frappe.db.set_single_value("CRM Privacy Settings", "head_of_compliance", head)
		frappe.db.set_value("User", head, "enabled", 0)
		frappe.db.set_value(DOCTYPE, self.r.name, {"ack_reminder_sent": 1, "day30_reminder_sent": 1})
		send_reminders(getdate("2026-12-05"))
		self.assertEqual(self.count(head), 0)
		self.assertEqual(self.count(self.officer), 1)

	def test_day40_goes_only_to_head(self):
		head = make_user("head@example.com", ["Sales Manager"]).name
		frappe.db.set_single_value("CRM Privacy Settings", "head_of_compliance", head)
		frappe.db.set_value(DOCTYPE, self.r.name, {"ack_reminder_sent": 1, "day30_reminder_sent": 1})
		send_reminders(getdate("2026-12-05"))
		self.assertEqual(self.count(head), 1)
		self.assertEqual(self.count(self.officer), 0)

	def test_subject_names_only_the_request(self):
		send_reminders(getdate("2026-12-06"))
		texts = frappe.get_all(
			"CRM Notification", filters={"notification_type_doc": self.r.name}, pluck="notification_text"
		)
		self.assertTrue(texts)
		for text in texts:
			self.assertTrue(text.startswith(f"Erasure request {self.r.name}: "), text)

	def test_closed_requests_ignored(self):
		frappe.db.set_value(DOCTYPE, self.r.name, "status", "Closed")
		send_reminders(getdate("2026-12-06"))
		self.assertEqual(self.count(self.officer), 0)

	def test_one_failing_request_does_not_stop_the_others(self):
		other = make_request(date_received="2026-10-26")
		real_notify = reminders.notify

		def flaky(users, subject, request, *args, **kwargs):
			if request == self.r.name:
				raise RuntimeError("boom")
			return real_notify(users, subject, request, *args, **kwargs)

		with patch("crm.privacy.reminders.notify", flaky), patch("frappe.log_error") as log_error:
			send_reminders(getdate("2026-11-04"))

		self.assertEqual(self.count(self.officer), 0)
		self.assertFalse(self.flag("ack_reminder_sent"))
		self.assertEqual(
			frappe.db.count(
				"CRM Notification", {"to_user": self.officer, "notification_type_doc": other.name}
			),
			1,
		)
		log_error.assert_called_once()
		self.assertEqual(log_error.call_args.kwargs["title"], f"Erasure reminder failed for {self.r.name}")
