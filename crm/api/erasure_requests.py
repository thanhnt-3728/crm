# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Lifecycle API of CRM Erasure Request. Phase 07 builds against these signatures: do not change them.

Visibility is the controller's and `request_visibility`'s job (design 5.1); these functions check permission
explicitly, then write inside `server_write()` so the guarded fields can be set."""

from datetime import date

import frappe
from frappe import _
from frappe.utils import today

from crm.privacy.hold_actions import recheck, submit, submitted_row
from crm.privacy.identifier_sync import apply_confirmation, identifier_impact, set_excluded
from crm.privacy.matching import refresh_suggestions
from crm.privacy.on_hold import add_owner_names, dispatch, evaluate_hold
from crm.privacy.request_intake import add_source, add_typed_identifiers
from crm.privacy.request_scope import hide_unreadable
from crm.privacy.request_status import CLOSED, EDITABLE_STATUSES, LOGGED, assert_not_frozen, server_write
from crm.privacy.request_visibility import (
	DOCTYPE,
	INTERNAL_FIELDS,
	available_actions,
	days_left,
	sees_all,
	trim_for_user,
)

EDITABLE_FIELDS = ("channel", "date_received", "requester_names", "original_message")
IDENTIFIER_VALUES = ("emails", "phones")


def request_response(doc) -> dict:
	"""The full request as `get_request` returns it: the document, `days_left` and the `can` flags."""
	data = frappe._dict((k, v) for k, v in doc.as_dict().items() if k not in INTERNAL_FIELDS)
	data["days_left"] = days_left(doc.respond_by)
	add_owner_names(doc, data)
	user = frappe.session.user
	data["can"] = available_actions(doc, user)
	if not sees_all(user):  # RT-5
		hide_unreadable(data, user)
	return data


def _open_request(name: str):
	"""The request for an edit by the logger (while Logged) or Compliance, before the erasure."""
	doc = frappe.get_doc(DOCTYPE, name)
	doc.check_permission("write")
	assert_not_frozen(doc.erasure_job_status)
	if doc.status not in EDITABLE_STATUSES:
		frappe.throw(_("A request that is {0} can no longer be edited").format(_(doc.status)))
	return doc


def _save(doc) -> None:
	with server_write():
		doc.save()


@frappe.whitelist()
def create_request(
	source_doctype: str | None,
	source_name: str | None,
	contact: str | None,
	channel: str,
	date_received: str,
	requester_names: str | None,
	emails: list | None,
	phones: list | None,
	original_message: str | None,
) -> str:
	"""Log a request from a lead, deal or contact (prefilled and pre-confirmed) or from a blank form.
	`contact` picks the person on a deal and is required when the deal lists more than one."""
	frappe.has_permission(DOCTYPE, "create", throw=True)
	doc = frappe.new_doc(DOCTYPE)
	doc.update(
		{
			"channel": channel,
			"date_received": date_received or today(),
			"requester_names": requester_names,
			"original_message": original_message,
		}
	)
	add_typed_identifiers(doc, emails, phones)
	if source_doctype or source_name:
		person = add_source(doc, source_doctype, source_name, contact)
		doc.requester_names = doc.requester_names or person
	with server_write():
		doc.insert()
	return doc.name


@frappe.whitelist()
def get_request(name: str) -> dict:
	"""The request in full with `days_left` and `can`. Raises PermissionError for a logger once
	it is submitted."""
	doc = frappe.get_doc(DOCTYPE, name)
	doc.check_permission("read")
	return request_response(doc)


@frappe.whitelist()
def list_requests() -> list[dict]:
	"""Compliance and Sales Managers get every request in full. Everyone else gets their own Logged requests
	in full and their submitted ones as `{name, status, acknowledge_by, respond_by, days_left}` only.
	Open requests come first by `respond_by`, then the closed ones."""
	frappe.has_permission(DOCTYPE, "read", throw=True)
	user = frappe.session.user
	# get_all on purpose: get_list hides a logger's submitted requests; only their status and dates leave here.
	sees_everything = sees_all(user)
	filters = None if sees_everything else {"logged_by": user}
	rows = []
	for row in frappe.get_all(DOCTYPE, filters=filters, fields=["*"]):
		row["days_left"] = days_left(row.respond_by)
		rows.append(trim_for_user(row, sees_everything))

	def due(row):
		return row.respond_by or date.max

	open_rows = sorted((r for r in rows if r.status != CLOSED), key=due)
	closed_rows = sorted((r for r in rows if r.status == CLOSED), key=due, reverse=True)
	return open_rows + closed_rows


@frappe.whitelist()
def update_request(name: str, values: dict) -> dict:
	"""Edit `channel`, `date_received`, `requester_names` and `original_message`, and add typed `emails` /
	`phones` as identifiers. Anything else is refused. The logger may do this only while the request is
	Logged, Compliance until the request is Erased or Declined. Returns the request as `get_request` does."""
	doc = _open_request(name)
	values = values or {}
	for key in values:
		if key not in EDITABLE_FIELDS + IDENTIFIER_VALUES:
			frappe.throw(_("{0} cannot be edited").format(key))
	for key in IDENTIFIER_VALUES:
		if values.get(key) is not None and not isinstance(values[key], list):
			frappe.throw(_("{0} must be a list").format(key))
	for fieldname in EDITABLE_FIELDS:
		if fieldname in values:
			doc.set(fieldname, values[fieldname])
	add_typed_identifiers(doc, values.get("emails"), values.get("phones"))
	_save(doc)
	return request_response(doc)


@frappe.whitelist()
def suggest_matches(name: str) -> dict:
	"""Add unconfirmed rows for readable records that match a kept identifier or follow from a confirmed one."""
	doc = _open_request(name)
	if refresh_suggestions(doc, frappe.session.user):
		_save(doc)
	return request_response(doc)


@frappe.whitelist()
def set_match_confirmed(name: str, row: str, confirmed: bool) -> dict:
	"""Confirm or unconfirm a match row. Adds `skipped_identifiers`: unusable values on a newly confirmed record."""
	doc = _open_request(name)
	skipped = apply_confirmation(doc, row, confirmed, frappe.session.user)
	_save(doc)
	if doc.status != LOGGED:  # Awaiting sign-off or On Hold: an open deal confirmed now holds the request
		dispatch(evaluate_hold(doc))
	return {**request_response(doc), "skipped_identifiers": skipped}


@frappe.whitelist()
def set_identifier_excluded(name: str, row: str, excluded: bool) -> dict:
	"""Exclude an identifier (a shared line or inbox) from matching, the sweep and blocking, or take it back."""
	doc = _open_request(name)
	set_excluded(doc, row, excluded)
	_save(doc)
	return request_response(doc)


@frappe.whitelist()
def get_identifier_impact(name: str) -> list[dict]:
	"""Per identifier: `row`, `kind`, `value`, `excluded`, `records` (readable ones) and, for Compliance only,
	`communications` and `call_logs` (None for others)."""
	return identifier_impact(_open_request(name), frappe.session.user)


@frappe.whitelist()
def submit_request(name: str) -> dict:
	"""Send a Logged request to Compliance: it becomes On Hold when an open deal still lists the person (or is
	confirmed), else Awaiting sign-off. The logger gets only the status and due dates back."""
	doc = _open_request(name)
	submit(doc)
	return request_response(doc) if sees_all(frappe.session.user) else submitted_row(doc)


@frappe.whitelist()
def recheck_hold(name: str) -> dict:
	"""Compliance only: look at the open deals again now; the request moves between On Hold and Awaiting sign-off."""
	doc = frappe.get_doc(DOCTYPE, name)
	recheck(doc, frappe.session.user)
	return request_response(doc)
