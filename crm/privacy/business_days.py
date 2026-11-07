# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Business days (Mon-Fri, excluding US federal holidays) for the CCPA deadlines.

Holidays are computed from their statutory rules (5 U.S.C. 6103), so nothing needs yearly
upkeep. A holiday falling on a Saturday is observed the Friday before (which can land in the
previous year: Jan 1 2022 -> Dec 31 2021), one on a Sunday the Monday after. Pure: no DB.
"""

from datetime import date, timedelta
from functools import lru_cache

MON, THU = 0, 3

ACKNOWLEDGE_BUSINESS_DAYS = 10
RESPOND_CALENDAR_DAYS = 45


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
	first = date(year, month, 1)
	return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
	next_month = date(year + month // 12, month % 12 + 1, 1)
	last = next_month - timedelta(days=1)
	return last - timedelta(days=(last.weekday() - weekday) % 7)


# (first year in force, rule(year) -> actual date). Adding a holiday is one line.
HOLIDAY_RULES = [
	(1870, lambda y: date(y, 1, 1)),  # New Year's Day
	(1986, lambda y: _nth_weekday(y, 1, MON, 3)),  # Birthday of Martin Luther King, Jr.
	(1971, lambda y: _nth_weekday(y, 2, MON, 3)),  # Washington's Birthday
	(1971, lambda y: _last_weekday(y, 5, MON)),  # Memorial Day
	(2021, lambda y: date(y, 6, 19)),  # Juneteenth National Independence Day
	(1870, lambda y: date(y, 7, 4)),  # Independence Day
	(1894, lambda y: _nth_weekday(y, 9, MON, 1)),  # Labor Day
	(1971, lambda y: _nth_weekday(y, 10, MON, 2)),  # Columbus Day
	(1938, lambda y: date(y, 11, 11)),  # Veterans Day
	(1942, lambda y: _nth_weekday(y, 11, THU, 4)),  # Thanksgiving Day
	(1870, lambda y: date(y, 12, 25)),  # Christmas Day
]


def _observed(day: date) -> date:
	if day.weekday() == 5:  # Saturday -> Friday
		return day - timedelta(days=1)
	if day.weekday() == 6:  # Sunday -> Monday
		return day + timedelta(days=1)
	return day


@lru_cache(maxsize=64)
def _holidays_cached(year: int) -> frozenset[date]:
	observed = set()
	# The next year's New Year's Day can be observed on Dec 31 of this year.
	for rule_year in (year, year + 1):
		for since, rule in HOLIDAY_RULES:
			if rule_year >= since:
				day = _observed(rule(rule_year))
				if day.year == year:
					observed.add(day)
	return frozenset(observed)


def us_federal_holidays(year: int) -> set[date]:
	"""Observed US federal holidays that fall within ``year``."""
	return set(_holidays_cached(year))


def is_business_day(day: date) -> bool:
	return day.weekday() < 5 and day not in _holidays_cached(day.year)


def _step_business_days(day: date, n: int, direction: int) -> date:
	if n < 0:
		raise ValueError("n must be zero or positive")
	while n:
		day += timedelta(days=direction)
		if is_business_day(day):
			n -= 1
	return day


def add_business_days(day: date, n: int) -> date:
	"""The n-th business day after ``day`` (counting starts the day after)."""
	return _step_business_days(day, n, 1)


def subtract_business_days(day: date, n: int) -> date:
	"""The n-th business day before ``day``."""
	return _step_business_days(day, n, -1)


def acknowledge_by(received: date) -> date:
	return add_business_days(received, ACKNOWLEDGE_BUSINESS_DAYS)


def respond_by(received: date) -> date:
	return received + timedelta(days=RESPOND_CALENDAR_DAYS)
