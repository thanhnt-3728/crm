# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from datetime import date

from frappe.tests import UnitTestCase

from crm.fcrm.doctype.crm_erasure_request.erasure_deadlines import add_business_days, compute_due_dates


class TestErasureDeadlines(UnitTestCase):
	def test_dana_example_from_the_emails(self):
		"""Received Mon 2026-10-26 -> ack Mon 2026-11-09, response Thu 2026-12-10"""
		self.assertEqual(
			compute_due_dates(date(2026, 10, 26), set()), (date(2026, 11, 9), date(2026, 12, 10))
		)

	def test_business_day_table(self):
		cases = [
			# (received, holidays, expected ack due)
			(date(2026, 10, 30), set(), date(2026, 11, 13)),  # Friday
			(date(2026, 10, 31), set(), date(2026, 11, 13)),  # Saturday: Mon Nov 2 is day 1
			(date(2026, 11, 1), set(), date(2026, 11, 13)),  # Sunday
			(date(2026, 10, 26), {date(2026, 11, 3)}, date(2026, 11, 10)),  # holiday inside the window
			(date(2026, 10, 26), {date(2026, 11, 9)}, date(2026, 11, 10)),  # holiday on day 10
			(date(2026, 10, 26), {date(2026, 10, 26)}, date(2026, 11, 9)),  # holiday on day 0 is not counted
			(date(2026, 10, 26), {date(2026, 10, 31)}, date(2026, 11, 9)),  # holiday on a weekend: no shift
			(date(2026, 12, 21), set(), date(2027, 1, 4)),  # year rollover
			(date(2027, 1, 28), set(), date(2027, 2, 11)),  # month rollover
		]
		for received, holidays, expected in cases:
			with self.subTest(received=received, holidays=holidays):
				self.assertEqual(add_business_days(received, 10, holidays), expected)

	def test_response_due_is_45_calendar_days(self):
		cases = [
			(date(2026, 10, 31), date(2026, 12, 15)),  # Saturday counts as received
			(date(2026, 12, 21), date(2027, 2, 4)),  # year rollover
			(date(2028, 1, 20), date(2028, 3, 5)),  # leap year February
		]
		for received, expected in cases:
			with self.subTest(received=received):
				self.assertEqual(compute_due_dates(received, {date(2026, 11, 3)})[1], expected)

	def test_zero_days_and_invalid_input(self):
		self.assertEqual(add_business_days(date(2026, 10, 26), 0, set()), date(2026, 10, 26))
		with self.assertRaises(ValueError):
			add_business_days(date(2026, 10, 26), -1, set())
		with self.assertRaises(ValueError):
			compute_due_dates(None, set())
