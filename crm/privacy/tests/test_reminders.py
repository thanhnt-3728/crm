# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Which reminders are due on a given day (phase 06 step 1; design 5.5). Pure: no database."""

from datetime import date

from frappe.tests import UnitTestCase

from crm.privacy.reminders import due_reminders

NO_FLAGS = {
	"status": "Awaiting sign-off",
	"acknowledgment_sent": 0,
	"ack_reminder_sent": 0,
	"day30_reminder_sent": 0,
	"day40_alert_sent": 0,
}


def row(**values):
	"""The design's example: received Oct 26 2026, so acknowledge by Nov 9."""
	return {"date_received": date(2026, 10, 26), "acknowledge_by": date(2026, 11, 9), **NO_FLAGS, **values}


class TestDueReminders(UnitTestCase):
	def due(self, day, **values):
		return due_reminders(row(**values), day)

	def test_nothing_is_due_before_the_first_date(self):
		self.assertEqual(self.due(date(2026, 11, 3)), [])

	def test_the_acknowledgment_reminder_is_due_three_business_days_before_acknowledge_by(self):
		self.assertEqual(self.due(date(2026, 11, 3)), [])
		self.assertEqual(self.due(date(2026, 11, 4)), ["ack"])  # Nov 9 minus 3 business days

	def test_day_30_and_day_40_fall_on_received_plus_30_and_40(self):
		self.assertEqual(self.due(date(2026, 11, 24), ack_reminder_sent=1), [])
		self.assertEqual(self.due(date(2026, 11, 25), ack_reminder_sent=1), ["day30"])
		self.assertEqual(self.due(date(2026, 12, 4), ack_reminder_sent=1, day30_reminder_sent=1), [])
		self.assertEqual(self.due(date(2026, 12, 5), ack_reminder_sent=1, day30_reminder_sent=1), ["day40"])

	def test_an_acknowledged_request_gets_no_acknowledgment_reminder(self):
		self.assertEqual(self.due(date(2026, 11, 9), acknowledgment_sent=1), [])

	def test_a_reminder_that_was_sent_is_not_due_again(self):
		sent = {"ack_reminder_sent": 1, "day30_reminder_sent": 1, "day40_alert_sent": 1}
		self.assertEqual(self.due(date(2027, 1, 1), **sent), [])

	def test_a_request_logged_late_gets_everything_that_is_already_due_at_once(self):
		day = date(2026, 12, 1)  # day 36: acknowledgment and day 30 are past, day 40 is not
		self.assertEqual(self.due(day), ["ack", "day30"])
		self.assertEqual(self.due(date(2027, 3, 1)), ["ack", "day30", "day40"])

	def test_a_closed_request_gets_nothing(self):
		self.assertEqual(self.due(date(2027, 3, 1), status="Closed"), [])

	def test_a_request_with_no_stored_deadline_uses_the_computed_one(self):
		self.assertEqual(self.due(date(2026, 11, 4), acknowledge_by=None), ["ack"])

	def test_a_date_that_is_still_a_string_is_read(self):
		self.assertEqual(self.due("2026-11-25", ack_reminder_sent=1, date_received="2026-10-26"), ["day30"])
