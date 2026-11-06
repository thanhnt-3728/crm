# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
"""Erasure request endpoints (phase 02 F5): permission checks, then calls into `crm.erasure`

All endpoints are POST-only (they write, or run discovery's table scans).
Match keys sent to and returned by these endpoints have the form "<ref_doctype>::<ref_name>"
(`crm.erasure.match_rows.format_key` / `parse_key`), e.g. "Communication::7f3a9c1e2b".
Every endpoint returning a preview returns `crm.erasure.preview.preview(request)`:
    {name, status, hold_reason, ack_due, response_due,
     groups: [{doctype, count, excluded, unreadable,
               rows: [{key, ref_doctype, ref_name, title, reason, action, excluded, new_since_logging}]}],
     hidden: {doctype: count},
     identifiers_not_on_subject: [{kind, position}]}  # identifiers found nowhere on her records (L1)
`rows` lists only records the caller may read; the others are counted in `unreadable` and can be
excluded only by someone who may read them. Identifiers are never echoed or logged; errors about
them name only their position.
"""

import frappe
from frappe import _

from crm.erasure.approval import (  # noqa: F401 -- whitelisted approval endpoints (phase 03)
	approve,
	close,
	get_approval_preview,
	reject,
	retry_execution,
)
from crm.erasure.discovery import discover
from crm.erasure.identifiers import Identifiers, identifier_rows
from crm.erasure.match_rows import VIA_EXCLUDED, hand_excluded, match_key, parse_key, plan_exclusions
from crm.erasure.preview import preview, readable_keys
from crm.erasure.source_identifiers import identifiers_match_source
from crm.fcrm.doctype.crm_erasure_request.erasure_guards import assert_can_decide
from crm.fcrm.doctype.crm_erasure_request.erasure_request_lifecycle import assert_identifier_on_source
from crm.fcrm.doctype.crm_erasure_request.erasure_states import DRAFT, HOLD_STATES, PRIVACY_OFFICER_ROLE

REQUEST = "CRM Erasure Request"
SOURCE_DOCTYPES = ("CRM Lead", "CRM Deal", "Contact")


@frappe.whitelist(methods=["POST"])
def log_request(
	source_doctype: str,
	source_docname: str,
	subject_name: str,
	received_on: str,
	emails: list[str] | None = None,
	phones: list[str] | None = None,
) -> dict:
	"""Log a Draft request for the person behind a Lead, Deal or Contact, with its first matches"""
	frappe.has_permission(REQUEST, "create", throw=True)
	_assert_can_read_source(source_doctype, source_docname)
	rows = _identifier_rows(emails, phones)
	if not identifiers_match_source(source_doctype, source_docname, Identifiers.from_rows(rows)):
		frappe.throw(
			_("None of the identifiers is on {0} {1}: add one recorded there").format(
				_(source_doctype), source_docname
			)
		)
	request = frappe.get_doc(
		{
			"doctype": REQUEST,
			"subject_name": subject_name,
			"source_doctype": source_doctype,
			"source_docname": source_docname,
			"received_on": received_on,
			"identifiers": [{"kind": row["kind"], "value": row["value"]} for row in rows],
		}
	).insert()
	request.set_identifiers(rows)
	found = _discover(request)
	request.replace_matches(found.matches)
	return preview(request, found.hidden)


@frappe.whitelist(methods=["POST"])
def refresh_matches(name: str) -> dict:
	"""Re-run discovery; rows found since the last run are flagged, exclusions are kept"""
	request = _load(name, "write")
	_assert_match_editor(request)
	assert_identifier_on_source(request)  # never discover for identifiers that are not hers
	return _replan(request, hand_excluded(request.matches))


@frappe.whitelist(methods=["POST"])
def set_exclusions(name: str, excluded: list[str]) -> dict:
	"""Exclude exactly the readable matches named by `excluded` keys (Draft only, by its requester)

	Stored rows are never dropped. Rows reachable only through an excluded match are excluded
	with reason "via_excluded" (their keys, if sent back, are ignored) and return to their own
	state when that match is included again. Exclusions on rows the caller cannot read are kept.
	"""
	request = _load(name, "write")
	_assert_requester(request)
	if request.status != DRAFT:
		frappe.throw(_("Exclusions can be changed only while the request is a Draft"))
	try:
		keys = {parse_key(key) for key in excluded or []}
	except ValueError:
		keys = None
	readable = readable_keys(request)
	if keys is None or not keys <= readable:
		frappe.throw(_("One of the excluded keys is not a match of {0}").format(request.name))
	via_parent = {match_key(row) for row in request.matches if row.reason == VIA_EXCLUDED}
	hand = (keys - via_parent) | (hand_excluded(request.matches) - readable)
	return _replan(request, hand)


@frappe.whitelist(methods=["POST"])
def submit_for_approval(name: str) -> dict:
	"""Draft -> Pending Approval, or On Hold while one of her deals is open"""
	request = _load(name, "write")
	request.submit_for_approval()
	return {"name": request.name, "status": request.status, "hold_reason": request.hold_reason}


@frappe.whitelist(methods=["POST"])
def get_preview(name: str) -> dict:
	"""Grouped matches and hidden-copy counts; for the requester or a Privacy Officer"""
	request = _load(name, "read")
	user = frappe.session.user
	if user != request.requested_by and PRIVACY_OFFICER_ROLE not in frappe.get_roles(user):
		frappe.throw(
			_("Only the requester or a Privacy Officer can preview {0}").format(name), frappe.PermissionError
		)
	return preview(request)


def _load(name: str, ptype: str):
	if not name or not frappe.db.exists(REQUEST, name):
		frappe.throw(_("Erasure request {0} not found").format(name), frappe.DoesNotExistError)
	request = frappe.get_doc(REQUEST, name)
	frappe.has_permission(REQUEST, ptype, doc=request, throw=True)
	return request


def _assert_requester(request) -> None:
	if frappe.session.user != request.requested_by:
		frappe.throw(_("Only the requester can change {0}").format(request.name), frappe.PermissionError)


def _assert_match_editor(request) -> None:
	"""Who may re-run discovery, checked before it runs: the requester on a Draft (who must still
	read the source), a decider while it waits for approval"""
	if request.status == DRAFT:
		_assert_requester(request)
		_assert_can_read_source(request.source_doctype, request.source_docname)
	elif request.status in HOLD_STATES:
		assert_can_decide(request)
	else:
		frappe.throw(_("Matches of {0} are final once it is approved").format(request.name))


def _assert_can_read_source(doctype: str, docname: str) -> None:
	"""Missing and unreadable sources get the same answer, so the endpoint reveals nothing"""
	exists = doctype in SOURCE_DOCTYPES and docname and frappe.db.exists(doctype, docname)
	if not exists or not frappe.has_permission(doctype, "read", doc=docname):
		frappe.throw(
			_("{0} {1} not found or not permitted").format(_(doctype), docname), frappe.PermissionError
		)


def _identifier_rows(emails: list[str] | None, phones: list[str] | None) -> list[dict]:
	try:
		rows = identifier_rows(emails or [], phones or [])
	except ValueError as e:
		frappe.throw(_("Check the identifiers: {0}").format(str(e)))  # position only, never the value
	if not rows:
		frappe.throw(_("Add at least one email address or phone number of the person"))
	return rows


def _replan(request, hand: set) -> dict:
	"""Store the rows `hand` exclusions call for (two discovery runs: all reachable, and honouring
	`hand`) and return the preview"""
	reachable, aware = _discover(request, set()), _discover(request, hand)
	request.replace_matches(plan_exclusions(request.matches, hand, reachable.matches, aware.matches))
	return preview(request, aware.hidden)


def _discover(request, excluded: set | None = None):
	try:
		return discover(request, excluded)
	except ValueError:  # a stored identifier no longer normalizes; never echo it
		frappe.throw(_("An identifier stored on {0} is not valid; correct the request").format(request.name))
