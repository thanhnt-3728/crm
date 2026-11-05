"""Deadline arithmetic for CCPA erasure requests.

Pure standard-library date maths, no frappe and no database access.

- Respond within 45 calendar days of receipt.
- Acknowledge within 10 US business days of receipt (Mon-Fri, excluding US federal
  holidays on their observed dates). Counting starts the day after receipt.
"""

from datetime import date, timedelta

ACKNOWLEDGE_BUSINESS_DAYS = 10
RESPOND_CALENDAR_DAYS = 45

MONDAY, THURSDAY, SATURDAY, SUNDAY = 0, 3, 5, 6


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
	"""The n-th `weekday` (Mon=0) of the month."""
	first = date(year, month, 1)
	offset = (weekday - first.weekday()) % 7
	return first + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
	"""The last `weekday` (Mon=0) of the month."""
	if month == 12:
		last = date(year, 12, 31)
	else:
		last = date(year, month + 1, 1) - timedelta(days=1)
	return last - timedelta(days=(last.weekday() - weekday) % 7)


def _observed(d: date) -> date:
	"""Saturday holidays are observed on Friday, Sunday holidays on Monday."""
	if d.weekday() == SATURDAY:
		return d - timedelta(days=1)
	if d.weekday() == SUNDAY:
		return d + timedelta(days=1)
	return d


def us_federal_holidays(year: int) -> set[date]:
	"""US federal holidays for `year`, as observed dates.

	Includes next year's Jan 1 when it is observed on Dec 31 of `year`.
	"""
	holidays = {
		_observed(date(year, 1, 1)),  # New Year's Day (Jan 1 or, if on Sunday, Jan 2)
		_nth_weekday(year, 1, MONDAY, 3),  # Martin Luther King Jr. Day
		_nth_weekday(year, 2, MONDAY, 3),  # Washington's Birthday
		_last_weekday(year, 5, MONDAY),  # Memorial Day
		_observed(date(year, 6, 19)),  # Juneteenth
		_observed(date(year, 7, 4)),  # Independence Day
		_nth_weekday(year, 9, MONDAY, 1),  # Labor Day
		_nth_weekday(year, 10, MONDAY, 2),  # Columbus Day
		_observed(date(year, 11, 11)),  # Veterans Day
		_nth_weekday(year, 11, THURSDAY, 4),  # Thanksgiving
		_observed(date(year, 12, 25)),  # Christmas
	}
	# Jan 1 on a Saturday is observed on Dec 31 of the previous year.
	holidays.discard(date(year - 1, 12, 31))
	next_new_year = _observed(date(year + 1, 1, 1))
	if next_new_year.year == year:
		holidays.add(next_new_year)
	return holidays


def is_business_day(d: date) -> bool:
	"""Monday to Friday and not a US federal holiday (observed date)."""
	return d.weekday() < SATURDAY and d not in us_federal_holidays(d.year)


def add_business_days(start: date, n: int) -> date:
	"""The `n`-th business day after `start`. Counting starts the day after `start`."""
	current = start
	remaining = n
	while remaining > 0:
		current += timedelta(days=1)
		if is_business_day(current):
			remaining -= 1
	return current


def subtract_business_days(end: date, n: int) -> date:
	"""The business day `n` business days before `end` (`end` itself is not counted)."""
	current = end
	remaining = n
	while remaining > 0:
		current -= timedelta(days=1)
		if is_business_day(current):
			remaining -= 1
	return current


def acknowledge_by(received: date) -> date:
	"""The 10th US business day after `received`."""
	return add_business_days(received, ACKNOWLEDGE_BUSINESS_DAYS)


def respond_by(received: date) -> date:
	"""`received` + 45 calendar days."""
	return received + timedelta(days=RESPOND_CALENDAR_DAYS)


def days_left(received: date, today: date) -> int:
	"""Calendar days from `today` to `respond_by(received)`. Negative once overdue."""
	return (respond_by(received) - today).days


def day_number(received: date, today: date) -> int:
	"""Calendar days elapsed since `received`: 0 on the day received, 30 on received + 30."""
	return (today - received).days
