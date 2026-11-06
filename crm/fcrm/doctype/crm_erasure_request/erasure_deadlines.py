# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
"""CCPA deadlines: acknowledge within 10 business days, respond within 45 calendar days"""

from collections.abc import Collection
from datetime import date, timedelta

import frappe
from frappe.utils import getdate

ACK_BUSINESS_DAYS = 10
RESPONSE_CALENDAR_DAYS = 45


def add_business_days(start: date, n: int, holidays: Collection[date]) -> date:
	"""The n-th business day after `start` (day 0 excluded); weekends and `holidays` are skipped"""
	if n < 0:
		raise ValueError("n must not be negative")
	day = start
	counted = 0
	while counted < n:
		day += timedelta(days=1)
		if day.weekday() < 5 and day not in holidays:
			counted += 1
	return day


def compute_due_dates(received_on: date, holidays: Collection[date]) -> tuple[date, date]:
	"""(ack_due, response_due) for a request received on `received_on`"""
	if not isinstance(received_on, date):
		raise ValueError("received_on must be a date")
	ack_due = add_business_days(received_on, ACK_BUSINESS_DAYS, holidays)
	return ack_due, received_on + timedelta(days=RESPONSE_CALENDAR_DAYS)


def load_erasure_holidays() -> set[date]:
	"""Dates of `FCRM Settings.erasure_holiday_list`; empty setting -> no holidays (weekends only)"""
	holiday_list = frappe.db.get_single_value("FCRM Settings", "erasure_holiday_list")
	if not holiday_list:
		return set()
	dates = frappe.get_all(
		"CRM Holiday",
		filters={"parent": holiday_list, "parenttype": "CRM Holiday List", "parentfield": "holidays"},
		pluck="date",
	)
	return {getdate(d) for d in dates if d}
