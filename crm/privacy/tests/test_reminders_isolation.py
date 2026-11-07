# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""One request that fails must not stop the daily reminder run (phase 06; V1)."""

from unittest.mock import patch

import frappe

from crm.privacy.tests.reminder_case import ReminderCase


class TestOneFailureDoesNotStopTheRun(ReminderCase):
	def test_a_request_whose_send_raises_stays_unflagged_and_the_others_still_go_out(self):
		bad, good = self.aged(31), self.aged(31)
		real = __import__("crm.privacy.notify", fromlist=["notify_users"]).notify_users

		def flaky(users, text, **kwargs):
			if kwargs["request"] == bad:
				raise RuntimeError(f"cannot reach Marisol Vega at m.vega@example.com for {bad}")
			return real(users, text, **kwargs)

		queued = len(frappe.local.message_log)
		with patch("crm.privacy.reminders.notify.notify_users", side_effect=flaky):
			self.run_job()
		self.assertEqual(self.notices(bad), [])
		self.assertEqual(tuple(self.flags(bad).values()), (0, 0, 0))
		self.assertEqual(self.users_told(good), {self.compliance, self.compliance2})
		self.assertEqual(tuple(self.flags(good).values()), (1, 1, 0))
		self.assertEqual(len(frappe.local.message_log), queued)

	def test_the_log_holds_the_request_number_and_the_exception_class_only(self):
		bad = self.aged(31)

		def boom(*args, **kwargs):
			raise RuntimeError("Marisol Vega m.vega@example.com")

		with patch("crm.privacy.reminders.notify.notify_users", side_effect=boom):
			self.run_job()
		self.assertEqual([(log.method, log.error) for log in self.new_logs()], [(bad, "RuntimeError")])

	def test_a_failed_request_is_retried_by_the_next_run(self):
		bad = self.aged(31)
		with patch("crm.privacy.reminders.notify.notify_users", side_effect=RuntimeError("x")):
			self.run_job()
		self.run_job()
		self.assertEqual(tuple(self.flags(bad).values()), (1, 1, 0))
		self.assertEqual(self.users_told(bad), {self.compliance, self.compliance2})

	def test_a_failure_in_the_second_reminder_rolls_back_the_first_one_too(self):
		bad = self.aged(31)
		real = __import__("crm.privacy.notify", fromlist=["notify_users"]).notify_users
		calls = []

		def second_fails(users, text, **kwargs):
			calls.append(text)
			if len(calls) == 2:
				raise RuntimeError("x")
			return real(users, text, **kwargs)

		with patch("crm.privacy.reminders.notify.notify_users", side_effect=second_fails):
			self.run_job()
		self.assertEqual(self.notices(bad), [])
		self.assertEqual(tuple(self.flags(bad).values()), (0, 0, 0))
