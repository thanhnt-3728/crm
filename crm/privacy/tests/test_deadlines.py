from datetime import date

from frappe.tests import UnitTestCase

from crm.privacy.deadlines import (
	acknowledge_by,
	add_business_days,
	days_left,
	is_business_day,
	reminder_dates,
	respond_by,
	us_federal_holidays,
)


class TestDeadlines(UnitTestCase):
	def test_spec_example(self):
		self.assertEqual(acknowledge_by(date(2026, 10, 26)), date(2026, 11, 9))
		self.assertEqual(respond_by(date(2026, 10, 26)), date(2026, 12, 10))

	def test_veterans_day_is_skipped(self):
		self.assertEqual(acknowledge_by(date(2026, 11, 5)), date(2026, 11, 20))

	def test_thanksgiving_is_skipped(self):
		self.assertEqual(acknowledge_by(date(2026, 11, 20)), date(2026, 12, 7))

	def test_holidays_2026(self):
		h = us_federal_holidays(2026)
		for d in [
			date(2026, 1, 1),
			date(2026, 1, 19),
			date(2026, 2, 16),
			date(2026, 5, 25),
			date(2026, 6, 19),
			date(2026, 7, 3),
			date(2026, 9, 7),
			date(2026, 10, 12),
			date(2026, 11, 11),
			date(2026, 11, 26),
			date(2026, 12, 25),
		]:
			self.assertIn(d, h)
		self.assertEqual(len(h), 11)

	def test_saturday_holidays_observed_friday(self):
		self.assertIn(date(2027, 6, 18), us_federal_holidays(2027))  # Juneteenth Sat
		self.assertIn(date(2027, 12, 24), us_federal_holidays(2027))  # Christmas Sat

	def test_new_year_observed_in_previous_year(self):
		self.assertFalse(is_business_day(date(2027, 12, 31)))  # Jan 1 2028 is a Saturday
		self.assertNotIn(date(2027, 12, 31), us_federal_holidays(2028))

	def test_sunday_holiday_observed_monday(self):
		self.assertFalse(is_business_day(date(2027, 7, 5)))  # Jul 4 2027 is a Sunday

	def test_add_business_days_backwards(self):
		self.assertEqual(add_business_days(date(2026, 11, 9), -3), date(2026, 11, 4))

	def test_days_left_and_overdue(self):
		self.assertEqual(days_left(date(2026, 10, 26), date(2026, 10, 26)), 45)
		self.assertEqual(days_left(date(2026, 10, 26), date(2026, 12, 12)), -2)

	def test_reminder_dates(self):
		self.assertEqual(
			reminder_dates(date(2026, 10, 26)),
			{
				"acknowledgment": date(2026, 11, 4),
				"day_30": date(2026, 11, 25),
				"day_40": date(2026, 12, 5),
			},
		)
