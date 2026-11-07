# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Everything the CRM dashboard shows, read as each user for "all time" and for the current month (phase 08).

`dashboard_snapshot(users)` returns one dict: the layout `get_dashboard` builds plus every chart `get_chart_options`
offers, per (user, period). Two snapshots that are equal mean no number on any dashboard moved.
"""

from unittest.mock import patch

import frappe
from frappe.utils import get_first_day, get_last_day, nowdate

from crm.api.dashboard import get_chart, get_chart_options, get_dashboard
from crm.privacy.tests.make_test_user import as_user

ALL_TIME = ("2000-01-01", "2099-12-31")
CHART_GROUPS = ("number_chart", "axis_chart", "donut_chart")


def periods() -> dict:
	return {"all time": ALL_TIME, "this month": (str(get_first_day(nowdate())), str(get_last_day(nowdate())))}


def chart_names() -> list[tuple[str, str]]:
	"""(chart type, chart name) for every chart the options dialog offers."""
	options = get_chart_options()
	return [(group, option["value"]) for group in CHART_GROUPS for option in options[group]]


def read_everything(from_date: str, to_date: str) -> dict:
	out = {"dashboard": get_dashboard(from_date, to_date)}
	for group, name in chart_names():
		out[f"{group}:{name}"] = get_chart(name, group, from_date, to_date)
	return out


def dashboard_snapshot(users: tuple[str, ...]) -> dict:
	"""{(user, period): {"dashboard": layout with data, "<group>:<chart>": data}}. `get_dashboard` commits when it
	has to create the default layout: that commit is switched off so it cannot keep a test's fixture."""
	snapshot = {}
	with patch.object(frappe.db, "commit"):
		for user in users:
			for label, (from_date, to_date) in periods().items():
				snapshot[(user, label)] = as_user(user, read_everything, from_date, to_date)
	return snapshot
