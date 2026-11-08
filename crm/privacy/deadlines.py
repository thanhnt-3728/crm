"""US business-day deadline math for privacy (erasure) requests.

Stdlib only: no frappe import, so it can be unit-tested without a site.

Business days are Monday to Friday excluding US federal holidays. A holiday that
falls on a Saturday is observed on the Friday before, one that falls on a Sunday
is observed on the Monday after.
"""

from datetime import date, timedelta
from functools import cache

RESPOND_WITHIN_DAYS = 45
ACKNOWLEDGE_WITHIN_BUSINESS_DAYS = 10
ACKNOWLEDGMENT_REMINDER_BUSINESS_DAYS_BEFORE = 3
DAY_30_REMINDER = 30
DAY_40_REMINDER = 40

MONDAY, THURSDAY = 0, 3


def _fixed(month: int, day: int):
	return lambda year: date(year, month, day)


def _nth_weekday(month: int, weekday: int, n: int):
	"""nth (1-based) given weekday of a month; n=-1 is the last one."""

	def rule(year: int) -> date:
		if n > 0:
			first = date(year, month, 1)
			offset = (weekday - first.weekday()) % 7
			return first + timedelta(days=offset + 7 * (n - 1))
		last = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
		return last - timedelta(days=(last.weekday() - weekday) % 7)

	return rule


# (name, rule(year) -> actual date, first year the holiday exists)
HOLIDAY_RULES = [
	("New Year's Day", _fixed(1, 1), 1),
	("Martin Luther King Jr. Day", _nth_weekday(1, MONDAY, 3), 1),
	("Washington's Birthday", _nth_weekday(2, MONDAY, 3), 1),
	("Memorial Day", _nth_weekday(5, MONDAY, -1), 1),
	("Juneteenth National Independence Day", _fixed(6, 19), 2021),
	("Independence Day", _fixed(7, 4), 1),
	("Labor Day", _nth_weekday(9, MONDAY, 1), 1),
	("Columbus Day", _nth_weekday(10, MONDAY, 2), 1),
	("Veterans Day", _fixed(11, 11), 1),
	("Thanksgiving Day", _nth_weekday(11, THURSDAY, 4), 1),
	("Christmas Day", _fixed(12, 25), 1),
]


def _observed(day: date) -> date:
	if day.weekday() == 5:  # Saturday
		return day - timedelta(days=1)
	if day.weekday() == 6:  # Sunday
		return day + timedelta(days=1)
	return day


@cache
def _holidays(year: int) -> dict:
	holidays = {}
	# The next year's New Year's Day may be observed on Dec 31 of this year.
	for actual_year in (year, year + 1):
		for name, rule, since in HOLIDAY_RULES:
			if actual_year < since:
				continue
			observed = _observed(rule(actual_year))
			if observed.year == year:
				holidays[observed] = name
	return holidays


def us_federal_holidays(year: int) -> dict:
	"""Observed US federal holidays falling in `year`, as {date: name}."""
	return dict(_holidays(year))


def is_business_day(day: date) -> bool:
	if day.weekday() >= 5:
		return False
	return day not in _holidays(day.year) and day not in _holidays(day.year + 1)


def add_business_days(start: date, n: int) -> date:
	"""Move `n` business days from `start` (negative goes back). Counting starts the day after (or before) `start`."""
	step = 1 if n >= 0 else -1
	remaining = abs(n)
	day = start
	while remaining:
		day += timedelta(days=step)
		if is_business_day(day):
			remaining -= 1
	return day


def acknowledge_by(received: date) -> date:
	return add_business_days(received, ACKNOWLEDGE_WITHIN_BUSINESS_DAYS)


def respond_by(received: date) -> date:
	return received + timedelta(days=RESPOND_WITHIN_DAYS)


def days_left(received: date, today: date) -> int:
	"""Calendar days until the response deadline; negative once overdue."""
	return (respond_by(received) - today).days


def reminder_dates(received: date) -> dict:
	return {
		"acknowledgment": add_business_days(
			acknowledge_by(received), -ACKNOWLEDGMENT_REMINDER_BUSINESS_DAYS_BEFORE
		),
		"day_30": received + timedelta(days=DAY_30_REMINDER),
		"day_40": received + timedelta(days=DAY_40_REMINDER),
	}
