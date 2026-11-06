# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
"""Lifecycle rules of a CRM Erasure Request outside the state machine: due dates, deletion, and
the check that the person behind the source owns one of the identifiers

The erasure registry (`crm.erasure`) is imported inside the functions: this module loads with the
doctype, which must work before the registry package is importable (install, early migrate).
"""

import frappe
from frappe import _
from frappe.utils import getdate

from crm.fcrm.doctype.crm_erasure_request.erasure_deadlines import compute_due_dates
from crm.fcrm.doctype.crm_erasure_request.erasure_states import DRAFT


def due_dates_changed(request, before) -> bool:
	"""Due dates are computed on insert and when received_on moves, never on later saves (a
	holiday list edited afterwards does not move a running request's deadlines)"""
	return before is None or getdate(before.received_on) != getdate(request.received_on)


def set_due_dates(request, holidays) -> None:
	request.ack_due, request.response_due = compute_due_dates(getdate(request.received_on), holidays)


def assert_identifier_on_source(request, rows=None) -> None:
	"""One identifier must be on the source record itself (as `log_request` checks): otherwise
	discovery would look up whoever else uses a stranger's email or phone"""
	from crm.erasure.identifiers import Identifiers
	from crm.erasure.source_identifiers import identifiers_match_source

	try:
		ids = Identifiers.from_rows(request.get("identifiers") if rows is None else rows)
	except ValueError:
		ids = None
	if not ids or not identifiers_match_source(request.source_doctype, request.source_docname, ids):
		frappe.throw(
			_("None of the identifiers of {0} is on {1} {2}").format(
				request.name, _(request.source_doctype), request.source_docname
			)
		)


def assert_deletable(request) -> None:
	"""on_trash: a request is the audit record of an erasure; only a Draft may be deleted"""
	stored = frappe.db.get_value(request.doctype, request.name, "status")
	if stored != DRAFT:
		frappe.throw(
			_("Erasure request {0} is {1}; only a Draft can be deleted").format(request.name, _(stored)),
			frappe.ValidationError,
		)


def forget_personal_data(request) -> None:
	"""after_delete: Frappe copies the in-memory document into Deleted Document right after this
	hook, so dropping identifiers, matches and the subject's name here keeps them out of the copy"""
	request.set("identifiers", [])
	request.set("matches", [])
	request.subject_name = None
