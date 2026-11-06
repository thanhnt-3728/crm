# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
"""Marisol fixture, execution: requests ready for approval or for the job (not a test module)

    fx = build_marisol()
    request = approved_marisol_request(fx, excluded=("comm_from_her",))   # labels of fx.names
    ...                                     # tearDown: rollback; cleanup_marisol(); cleanup_execution(fx)
"""

import os
from contextlib import contextmanager
from unittest.mock import patch

import frappe

from crm.erasure.discovery import discover
from crm.erasure.erasure_test_fixture_base import WON_STATUS, MarisolFixture
from crm.erasure.erasure_test_fixtures import HER_EMAILS, log_marisol_request
from crm.erasure.match_rows import match_key, plan_exclusions
from crm.fcrm.doctype.crm_erasure_request.erasure_test_fixtures import REP, approve, as_user, set_deal_status

REQUEST = "CRM Erasure Request"
# Sales dashboard numbers that must not move when her records are anonymized
DASHBOARD_METHODS = (
	"get_total_leads",
	"get_ongoing_deals",
	"get_won_deals",
	"get_average_won_deal_value",
	"get_average_deal_value",
	"get_sales_trend",
	"get_funnel_conversion",
	"get_deals_by_stage_axis",
	"get_leads_by_source",
	"get_deals_by_salesperson",
)


def pending_marisol_request(fx: MarisolFixture, excluded: tuple[str, ...] = (), close_open_deal=True):
	"""Pending Approval with discovered matches; `excluded`: fx.names labels the rep excluded"""
	if close_open_deal:  # her open deal, and the colleague's deal she is a contact on, hold it
		with as_user(REP):
			set_deal_status(fx.deal_open, WON_STATUS)
			set_deal_status(fx.colleague_deal, WON_STATUS)
	request = log_marisol_request(fx)
	with as_user(REP):
		request.replace_matches(discover(request).matches)
		if excluded:  # as `set_exclusions` plans them: rows reachable only through these go too
			names = {fx.names[label] for label in excluded}
			hand = {match_key(row) for row in request.matches if row.ref_name in names}
			reachable, aware = discover(request, set()), discover(request, hand)
			request.replace_matches(plan_exclusions(request.matches, hand, reachable.matches, aware.matches))
		request.submit_for_approval()
	return request


def approved_marisol_request(fx: MarisolFixture, excluded: tuple[str, ...] = ()):
	return approve(pending_marisol_request(fx, excluded))


def fixture_names(fx: MarisolFixture) -> set[str]:
	names = set(fx.names.values())
	for bucket in (fx.expected, fx.hidden, fx.near_misses):
		for doctype_names in bucket.values():
			names.update(doctype_names)
	return names


def cleanup_execution(fx: MarisolFixture):
	"""__global_search is MyISAM: re-indexed rows of fixture records survive the rollback"""
	frappe.db.delete("__global_search", {"name": ["in", sorted(fixture_names(fx))]})


@contextmanager
def commits_recorded():
	"""`frappe.db.commit` replaced by a recorder, so the test transaction (and its fixture) survives"""
	with patch.object(frappe.db, "commit") as commit:
		yield commit


def dashboard_numbers() -> dict:
	from crm.api import dashboard

	start, end = frappe.utils.add_months(frappe.utils.today(), -1), frappe.utils.today()
	numbers = {method: getattr(dashboard, method)(start, end, None) for method in DASHBOARD_METHODS}
	return _canonical(numbers)  # rows tied on a count come back in any order


def _canonical(value):
	if isinstance(value, dict):
		return {key: _canonical(item) for key, item in value.items()}
	if isinstance(value, list):
		return sorted((_canonical(item) for item in value), key=lambda item: frappe.as_json(item))
	return value


def her_identifier_strings() -> tuple[str, ...]:
	"""What must never appear in an outcome or an error: her emails and phone digits"""
	return (*(email.lower() for email in HER_EMAILS), "4155550123", "4155550177", "Marisol", "Reyes")


def write_disk_file(file_url: str, content: str = "erasure test") -> str:
	"""Create the file `file_url` points at (public /files or /private/files); returns its path"""
	folder = "private" if file_url.startswith("/private/") else "public"
	path = frappe.get_site_path(folder, "files", file_url.rsplit("/", 1)[-1])
	with open(path, "w") as handle:
		handle.write(content)
	return path


def remove_disk_file(path: str):
	if os.path.exists(path):
		os.remove(path)


def db_values(doctype: str, name: str, fields) -> dict:
	return frappe.db.get_value(doctype, name, list(fields), as_dict=True) or {}


def run_executor(request):
	"""`executor.run` as the job runs it (renames of her records are allowed only there)"""
	from crm.erasure import executor, jobs

	with jobs.running_erasure(request.name):
		return executor.run(request)


# Records that point at a fixture namesake (same name, another person): their rows may spell the name
NAMESAKE_REFERENCES = (
	("Comment", "reference_doctype", "reference_name"),
	("ToDo", "reference_type", "reference_name"),
	("CRM Notification", "reference_doctype", "reference_name"),
	("Notification Log", "document_type", "document_name"),
	("Email Queue", "reference_doctype", "reference_name"),
	("Version", "ref_doctype", "docname"),
)


def full_name_hits(fx: MarisolFixture, full_name: str) -> list[str]:
	"""Tables (all but the request's own) with a row spelling `full_name`, ignoring the namesakes'"""
	from crm.erasure import verify
	from crm.erasure.identifiers import Identifiers

	namesakes = {(doctype, name) for doctype, names in fx.near_misses.items() for name in names}
	excluded = set(namesakes)
	for doctype, doctype_column, name_column in NAMESAKE_REFERENCES:
		for ref_doctype, name in namesakes:
			rows = frappe.get_all(doctype, {doctype_column: ref_doctype, name_column: name}, pluck="name")
			excluded.update((doctype, str(row)) for row in rows)
	tables = frappe.db.sql(
		"select table_name from information_schema.tables where table_schema = database() "
		"and table_type = 'BASE TABLE'",
		pluck=True,
	)
	skip = ("tabCRM Erasure Request", "tabCRM Erasure Identifier")
	tables = [table for table in tables if table not in skip]
	return verify.residual_hits(Identifiers(), tables, excluded, tokens=(full_name,))
