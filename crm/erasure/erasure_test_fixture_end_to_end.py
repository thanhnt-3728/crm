# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
"""Marisol fixture, end to end: real edits (Version rows), dashboard snapshots, table digests (not a test module)

Extends `build_marisol` additively; the caller turns versioning on (`frappe.in_test` False) around
`add_tracked_edits` so Frappe writes Version rows as it does in production.
"""

import hashlib
import inspect
import json

import frappe
from frappe.utils import get_first_day, get_last_day, nowdate

from crm.erasure.erasure_test_fixture_base import HER_EMAILS, HER_PHONE_DATA, MarisolFixture
from crm.fcrm.doctype.crm_erasure_request.erasure_test_fixtures import REP, as_user, ensure_deal_status

LOST_STATUS = "Erasure Test Lost"
WIDE_RANGE = ("2000-01-01", "2100-12-31")
DASHBOARD_PARAMS = ["from_date", "to_date", "user"]


def add_tracked_edits(fx: MarisolFixture) -> list[str]:
	"""The rep edits her lead and a note on her deal with saves: the Version rows carry her data"""
	ensure_deal_status(LOST_STATUS, "Lost")
	with as_user(REP):
		lead = frappe.get_doc("CRM Lead", fx.lead)
		lead.phone = HER_PHONE_DATA[1]
		lead.save(ignore_permissions=True)
		note = frappe.get_doc("FCRM Note", fx.names["note_on_deal"])
		note.content = f"<p>Asked to be mailed at {HER_EMAILS[1]}</p>"
		note.save(ignore_permissions=True)
	versions = frappe.get_all(
		"Version",
		{"ref_doctype": ["in", ["CRM Lead", "FCRM Note"]], "docname": ["in", [lead.name, note.name]]},
		pluck="name",
	)
	return sorted(versions)


def dashboard_snapshot(users: tuple[str | None, ...]) -> dict[str, str]:
	"""Every dashboard endpoint taking (from_date, to_date, user), per user and date range, as JSON"""
	from crm.api import dashboard

	month = (str(get_first_day(nowdate())), str(get_last_day(nowdate())))
	endpoints = {
		name: function
		for name, function in inspect.getmembers(dashboard, inspect.isfunction)
		if name.startswith("get_")
		and function.__module__ == dashboard.__name__
		and list(inspect.signature(function).parameters) == DASHBOARD_PARAMS
	}
	snapshot = {}
	for user in users:
		for label, (start, end) in (("wide", WIDE_RANGE), ("month", month)):
			for name, function in sorted(endpoints.items()):
				snapshot[f"{name}|{user}|{label}"] = _json(function(start, end, user))
		snapshot[f"get_dashboard|{user}|default"] = _json(dashboard.get_dashboard(None, None, user))
	return snapshot


def table_digest(tables) -> dict[str, str]:
	"""sha256 of every row of `tables` (order-independent): a second run must leave them as they are"""
	digests = {}
	for table in sorted(tables):
		rows = sorted(_json(row) for row in frappe.db.sql(f"select * from `{table}`", as_dict=True))
		digests[table] = hashlib.sha256("\n".join(rows).encode()).hexdigest()
	return digests


def cleanup_end_to_end(request_name: str | None):
	"""__global_search is MyISAM: rows of the renamed records and of the request survive a rollback"""
	if request_name:
		frappe.db.sql(
			"delete from `__global_search` where name like %s or name = %s",
			(f"Erased {request_name}%", request_name),
		)


def _json(value) -> str:
	return json.dumps(value, sort_keys=True, default=str)
