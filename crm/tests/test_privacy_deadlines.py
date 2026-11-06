# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

from datetime import date

from frappe.tests import IntegrationTestCase

from crm.privacy.deadlines import (
	acknowledge_by,
	add_business_days,
	day_number,
	days_left,
	is_business_day,
	respond_by,
	subtract_business_days,
	us_federal_holidays,
)


class TestPrivacyDeadlines(IntegrationTestCase):
	def test_marisol_dates(self):
		self.assertEqual(acknowledge_by(date(2026, 10, 26)), date(2026, 11, 9))
		self.assertEqual(respond_by(date(2026, 10, 26)), date(2026, 12, 10))

	def test_holidays_2026(self):
		h = us_federal_holidays(2026)
		self.assertIn(date(2026, 7, 3), h)  # Jul 4 is Saturday, observed Fri
		self.assertIn(date(2026, 11, 26), h)  # Thanksgiving
		self.assertIn(date(2026, 6, 19), h)  # Juneteenth
		self.assertIn(date(2026, 11, 11), h)  # Veterans Day

	def test_jan1_on_saturday_observed_previous_dec31(self):
		self.assertIn(date(2021, 12, 31), us_federal_holidays(2021))

	def test_sunday_holiday_observed_monday(self):
		# Jul 4 2027 is a Sunday
		self.assertIn(date(2027, 7, 5), us_federal_holidays(2027))

	def test_ack_skips_thanksgiving(self):
		# received Mon Nov 16 2026: business days Nov 17..Dec 1 skipping Thu Nov 26
		self.assertEqual(acknowledge_by(date(2026, 11, 16)), date(2026, 12, 1))

	def test_days_left(self):
		self.assertEqual(days_left(date(2026, 10, 26), date(2026, 11, 6)), 34)
		self.assertEqual(days_left(date(2026, 10, 26), date(2026, 12, 12)), -2)

	def test_day_number(self):
		self.assertEqual(day_number(date(2026, 10, 26), date(2026, 10, 26)), 0)
		self.assertEqual(day_number(date(2026, 10, 26), date(2026, 11, 25)), 30)

	def test_subtract_business_days(self):
		self.assertEqual(subtract_business_days(date(2026, 11, 9), 3), date(2026, 11, 4))

	def test_is_business_day(self):
		self.assertTrue(is_business_day(date(2026, 11, 9)))  # Monday
		self.assertFalse(is_business_day(date(2026, 11, 7)))  # Saturday
		self.assertFalse(is_business_day(date(2026, 11, 26)))  # Thanksgiving

	def test_add_business_days_counts_from_day_after(self):
		self.assertEqual(add_business_days(date(2026, 11, 6), 1), date(2026, 11, 9))  # Fri -> Mon
