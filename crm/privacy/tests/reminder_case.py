# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Base case for the daily reminder job tests: users for every tier, and requests of a chosen age."""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, today

from crm.privacy.reminders import send_due_reminders
from crm.privacy.tests.error_log_watch import ErrorLogWatch
from crm.privacy.tests.make_test_user import RequestTestCase, force_request, make_request, make_user

DOCTYPE = "CRM Erasure Request"


class ReminderCase(ErrorLogWatch, RequestTestCase):
	def setUp(self):
		super().setUp()
		self.watch_error_logs()
		self.compliance2 = make_user("pdr.compliance2@example.com", roles=["Compliance"])
		self.enqueue = patch("frappe.enqueue")  # queueing mail must not fill the test bench's RQ queue
		self.enqueue.start()
		self.addCleanup(self.enqueue.stop)
		# The job commits after each request; a test must not commit its own fixtures.
		commit = patch("frappe.db.commit")
		self.commit = commit.start()
		self.addCleanup(commit.stop)

	def aged(self, days: int, **values) -> str:
		"""A request received `days` ago (the Mon-Fri deadlines then follow the real calendar)."""
		name = make_request(self.logger, date_received=add_days(today(), -days))
		if values:
			force_request(name, **values)
		return name

	def notices(self, *requests) -> list:
		return frappe.get_all(
			"CRM Notification",
			{"notification_type_doc": ["in", list(requests)], "type": "Compliance"},
			[
				"to_user",
				"notification_type_doc",
				"message",
				"reference_doctype",
				"reference_name",
				"from_user",
			],
		)

	def users_told(self, *requests) -> set:
		return {n.to_user for n in self.notices(*requests)}

	def flags(self, name):
		return frappe.db.get_value(
			DOCTYPE, name, ["ack_reminder_sent", "day30_reminder_sent", "day40_alert_sent"], as_dict=True
		)

	def run_job(self, **kwargs):
		send_due_reminders(**kwargs)
