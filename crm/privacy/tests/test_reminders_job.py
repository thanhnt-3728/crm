# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The daily reminder job against real requests (phase 06 step 2; design 5.5, V1)."""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, getdate

from crm.privacy.tests.make_test_user import make_user
from crm.privacy.tests.reminder_case import DOCTYPE, ReminderCase


class TestDailyJob(ReminderCase):
	def test_every_compliance_user_is_told_and_nobody_else(self):
		name = self.aged(31)  # acknowledgment and day 30 are due
		self.run_job()
		self.assertEqual(self.users_told(name), {self.compliance, self.compliance2})
		self.assertEqual(len(self.notices(name)), 4)  # two reminders for two users
		self.assertNotIn("Administrator", self.users_told(name))
		for user in (self.manager, self.logger, self.other):
			self.assertNotIn(user, self.users_told(name))

	def test_a_notice_names_the_request_and_dates_only_and_links_to_it(self):
		name = self.aged(31)
		self.run_job()
		for notice in self.notices(name):
			self.assertIn(name, notice.message)
			self.assertEqual((notice.reference_doctype, notice.reference_name), (DOCTYPE, name))
			self.assertFalse(notice.from_user)
			for bit in ("Marisol", "Vega", "marisol", "example.com"):
				self.assertNotIn(bit.lower(), notice.message.lower())

	def test_a_second_run_sends_nothing(self):
		name = self.aged(31)
		self.run_job()
		before = len(self.notices(name))
		queued = frappe.db.count("Email Queue")
		self.run_job()
		self.assertEqual(len(self.notices(name)), before)
		self.assertEqual(frappe.db.count("Email Queue"), queued)
		self.assertEqual(tuple(self.flags(name).values()), (1, 1, 0))

	def test_each_reminder_also_goes_out_as_an_email(self):
		name = self.aged(31)
		self.run_job()
		recipients = frappe.get_all(
			"Email Queue",
			{"reference_doctype": DOCTYPE, "reference_name": name},
			pluck="name",
		)
		self.assertEqual(len(recipients), 4)

	def test_an_acknowledged_request_gets_no_acknowledgment_reminder(self):
		name = self.aged(31, acknowledgment_sent=1)
		self.run_job()
		self.assertEqual(len(self.notices(name)), 2)  # day 30 only, two users
		self.assertEqual(tuple(self.flags(name).values()), (0, 1, 0))

	def test_a_request_that_is_early_gets_nothing(self):
		name = self.aged(1)
		self.run_job()
		self.assertEqual(self.notices(name), [])
		self.assertEqual(tuple(self.flags(name).values()), (0, 0, 0))

	def test_a_closed_request_gets_nothing(self):
		name = self.aged(50, status="Closed")
		self.run_job()
		self.assertEqual(self.notices(name), [])

	def test_the_reminders_follow_the_status_not_the_job_state(self):
		for status in ("Logged", "Awaiting sign-off", "On Hold", "Erased", "Declined"):
			with self.subTest(status=status):
				name = self.aged(31, status=status)
				self.run_job()
				self.assertEqual(self.users_told(name), {self.compliance, self.compliance2})

	def test_today_can_be_passed_so_dates_are_not_the_wall_clock(self):
		name = self.aged(0)
		self.run_job(today=add_days(getdate(), 31))
		self.assertEqual(tuple(self.flags(name).values()), (1, 1, 0))

	def test_no_compliance_user_means_nothing_sent_and_no_flag_so_it_retries(self):
		name = self.aged(31)
		with patch("crm.privacy.reminders.get_compliance_users", return_value=[]):
			self.run_job()
		self.assertEqual(self.notices(name), [])
		self.assertEqual(tuple(self.flags(name).values()), (0, 0, 0))
		self.run_job()
		self.assertEqual(tuple(self.flags(name).values()), (1, 1, 0))


class TestDay40Alert(ReminderCase):
	def set_head(self, user):
		frappe.db.set_single_value("CRM Privacy Settings", "head_of_compliance", user)

	def test_only_the_head_of_compliance_is_alerted(self):
		head = make_user("pdr.head@example.com", roles=["Sales Manager"])
		self.set_head(head)
		name = self.aged(41, acknowledgment_sent=1, day30_reminder_sent=1)
		self.run_job()
		self.assertEqual(self.users_told(name), {head})
		self.assertEqual(tuple(self.flags(name).values()), (0, 1, 1))

	def test_a_disabled_head_falls_back_to_all_compliance_users_and_is_logged(self):
		head = make_user("pdr.head@example.com", roles=["Sales Manager"], enabled=0)
		self.set_head(head)
		name = self.aged(41, acknowledgment_sent=1, day30_reminder_sent=1)
		self.run_job()
		self.assertEqual(self.users_told(name), {self.compliance, self.compliance2})
		self.assertEqual(self.flags(name).day40_alert_sent, 1)
		logs = self.new_logs(method=name)
		self.assertEqual(len(logs), 1)
		self.assertNotIn("Traceback", logs[0].error)

	def test_no_head_set_falls_back_the_same_way(self):
		self.set_head(None)
		name = self.aged(41, acknowledgment_sent=1, day30_reminder_sent=1)
		self.run_job()
		self.assertEqual(self.users_told(name), {self.compliance, self.compliance2})
		self.assertEqual(len(self.new_logs(method=name)), 1)

	def test_a_working_head_leaves_no_error_log(self):
		head = make_user("pdr.head@example.com", roles=["Sales Manager"])
		self.set_head(head)
		self.aged(41, acknowledgment_sent=1, day30_reminder_sent=1)
		self.run_job()
		self.assertEqual(self.new_logs(), [])
