# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Fix round 1 (M2, L3): "today" is the site's calendar day, and each request is committed on its own."""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, today

from crm.privacy.tests.make_test_user import force_request, make_request
from crm.privacy.tests.reminder_case import DOCTYPE, ReminderCase

TIMEZONE = "frappe.utils.data.get_system_timezone"
AHEAD, BEHIND = "Pacific/Kiritimati", "Pacific/Pago_Pago"  # UTC+14 and UTC-11: never the same calendar day


class TestSiteTimezone(ReminderCase):
	def day_in(self, zone: str) -> str:
		with patch(TIMEZONE, return_value=zone):
			return str(today())

	def test_the_two_zones_really_disagree_on_the_date(self):
		self.assertNotEqual(self.day_in(AHEAD), self.day_in(BEHIND))

	def test_day_30_follows_the_calendar_day_of_the_site_not_the_servers(self):
		with patch(TIMEZONE, return_value=AHEAD):
			received = add_days(today(), -30)  # day 30 is "today" where the site is ahead
			name = make_request(self.logger, date_received=received)
		force_request(name, acknowledgment_sent=1)
		with patch(TIMEZONE, return_value=BEHIND):
			self.run_job()
		self.assertEqual(frappe.db.get_value(DOCTYPE, name, "day30_reminder_sent"), 0)
		self.assertEqual(self.notices(name), [])
		with patch(TIMEZONE, return_value=AHEAD):
			self.run_job()
		self.assertEqual(frappe.db.get_value(DOCTYPE, name, "day30_reminder_sent"), 1)
		self.assertEqual(self.users_told(name), {self.compliance, self.compliance2})


class TestCommitPerRequest(ReminderCase):
	def test_each_request_is_committed_on_its_own_so_no_row_lock_outlives_it(self):
		self.aged(31), self.aged(31), self.aged(1)
		self.commit.reset_mock()
		self.run_job()
		self.assertEqual(self.commit.call_count, len(frappe.get_all(DOCTYPE, {"status": ["!=", "Closed"]})))
		self.assertGreaterEqual(self.commit.call_count, 3)
