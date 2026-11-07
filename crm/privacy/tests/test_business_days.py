# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Business-day and US federal holiday math behind the CCPA deadlines (design 5.4)."""

from datetime import date

from frappe.tests import UnitTestCase

from crm.privacy.business_days import (
	acknowledge_by,
	add_business_days,
	is_business_day,
	respond_by,
	subtract_business_days,
	us_federal_holidays,
)


class FederalHolidaysTest(UnitTestCase):
	def test_2026_holidays_with_observed_dates(self):
		self.assertEqual(
			us_federal_holidays(2026),
			{
				date(2026, 1, 1),  # New Year's Day (Thu)
				date(2026, 1, 19),  # MLK Day, 3rd Mon Jan
				date(2026, 2, 16),  # Washington's Birthday, 3rd Mon Feb
				date(2026, 5, 25),  # Memorial Day, last Mon May
				date(2026, 6, 19),  # Juneteenth (Fri)
				date(2026, 7, 3),  # Independence Day Sat Jul 4 -> observed Fri
				date(2026, 9, 7),  # Labor Day, 1st Mon Sep
				date(2026, 10, 12),  # Columbus Day, 2nd Mon Oct
				date(2026, 11, 11),  # Veterans Day (Wed)
				date(2026, 11, 26),  # Thanksgiving, 4th Thu Nov
				date(2026, 12, 25),  # Christmas (Fri)
			},
		)

	def test_saturday_holiday_is_observed_on_friday(self):
		self.assertIn(date(2026, 7, 3), us_federal_holidays(2026))
		self.assertNotIn(date(2026, 7, 4), us_federal_holidays(2026))
		self.assertFalse(is_business_day(date(2026, 7, 3)))

	def test_sunday_holiday_is_observed_on_monday(self):
		# Jul 4 2027 is a Sunday
		self.assertIn(date(2027, 7, 5), us_federal_holidays(2027))
		self.assertFalse(is_business_day(date(2027, 7, 5)))

	def test_new_year_on_saturday_is_observed_on_dec_31_of_prior_year(self):
		# Jan 1 2022 is a Saturday
		self.assertIn(date(2021, 12, 31), us_federal_holidays(2021))
		self.assertNotIn(date(2022, 1, 1), us_federal_holidays(2022))
		self.assertFalse(is_business_day(date(2021, 12, 31)))

	def test_thanksgiving_2026(self):
		self.assertIn(date(2026, 11, 26), us_federal_holidays(2026))

	def test_juneteenth_only_from_2021(self):
		self.assertNotIn(date(2020, 6, 19), us_federal_holidays(2020))
		self.assertIn(date(2021, 6, 18), us_federal_holidays(2021))  # Sat Jun 19 -> Fri


class BusinessDayMathTest(UnitTestCase):
	def test_weekend_is_not_a_business_day(self):
		self.assertFalse(is_business_day(date(2026, 10, 31)))  # Sat
		self.assertFalse(is_business_day(date(2026, 11, 1)))  # Sun
		self.assertTrue(is_business_day(date(2026, 11, 2)))  # Mon

	def test_marisol_acknowledge_by(self):
		# design 5.4: received Oct 26 2026 -> acknowledge by Nov 9 2026
		self.assertEqual(acknowledge_by(date(2026, 10, 26)), date(2026, 11, 9))

	def test_marisol_respond_by_is_45_calendar_days(self):
		self.assertEqual(respond_by(date(2026, 10, 26)), date(2026, 12, 10))

	def test_ack_reminder_is_three_business_days_before(self):
		self.assertEqual(subtract_business_days(date(2026, 11, 9), 3), date(2026, 11, 4))

	def test_counting_starts_the_day_after(self):
		# Mon -> next business day Tue
		self.assertEqual(add_business_days(date(2026, 11, 2), 1), date(2026, 11, 3))
		self.assertEqual(add_business_days(date(2026, 11, 2), 0), date(2026, 11, 2))

	def test_received_on_friday_skips_weekend(self):
		self.assertEqual(add_business_days(date(2026, 11, 6), 1), date(2026, 11, 9))

	def test_received_on_holiday_eve_skips_holiday(self):
		# Wed Nov 25 2026, Thanksgiving Thu Nov 26 -> Fri Nov 27
		self.assertEqual(add_business_days(date(2026, 11, 25), 1), date(2026, 11, 27))

	def test_received_on_weekend(self):
		# Sat Oct 31 2026 -> 10 business days: Nov 2..6 (5), Nov 9,10,12,13 (Nov 11 Veterans) (9), Nov 16 (10)
		self.assertEqual(acknowledge_by(date(2026, 10, 31)), date(2026, 11, 16))

	def test_window_crossing_year_end(self):
		# Mon Dec 28 2026: Dec 29,30,31, Jan 1 2027 holiday (Fri), Jan 4 -> 4th business day
		self.assertEqual(add_business_days(date(2026, 12, 28), 4), date(2027, 1, 4))

	def test_subtract_skips_weekend_and_holiday(self):
		# Mon Nov 30 2026 back 2: Fri Nov 27 (1), Thu Nov 26 holiday, Wed Nov 25 (2)
		self.assertEqual(subtract_business_days(date(2026, 11, 30), 2), date(2026, 11, 25))
