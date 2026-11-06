# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
"""Server guards: the two-person approval rule and the delete block on records under an open request"""

import frappe
from frappe import _

from crm.fcrm.doctype.crm_erasure_request.erasure_request_references import (
	has_requests_in,
	requests_referencing,
	rewrite_references,
)
from crm.fcrm.doctype.crm_erasure_request.erasure_states import EXECUTED, OPEN_STATES, TERMINAL_STATES, can_decide

ALL_STATES = (*OPEN_STATES, EXECUTED, *TERMINAL_STATES)

# frappe.flags key set (to the request name) while that request's erasure job runs
ERASURE_EXECUTION_FLAG = "erasure_execution"


def assert_can_decide(request) -> None:
	"""Throw PermissionError unless the session user may approve or reject `request`

	Trusts only `frappe.session.user` and its roles, never a user passed in by a caller.
	"""
	user = frappe.session.user
	identity = stored_identity(request)
	if not identity or not can_decide(user, frappe.get_roles(user), identity.requested_by, identity.owner):
		frappe.throw(
			_("Only a Privacy Officer other than the requester can approve or reject {0}").format(
				request.name
			),
			frappe.PermissionError,
		)


def stored_identity(request) -> frappe._dict | None:
	"""requested_by/owner as saved: identity checks never trust the in-memory document"""
	if not request.name:
		return None
	return frappe.db.get_value(request.doctype, request.name, ["requested_by", "owner"], as_dict=True)


def stored_requester(request) -> str | None:
	identity = stored_identity(request)
	return identity.requested_by if identity else None


def block_delete_for_open_request(doc, method=None) -> None:
	"""on_trash for CRM Lead, CRM Deal and Contact: refuse while an open request points at the doc"""
	requests = requests_referencing(doc.doctype, [doc.name], OPEN_STATES)
	if requests:
		frappe.throw(
			_("{0} {1} cannot be deleted while erasure request {2} is open").format(
				_(doc.doctype), doc.name, ", ".join(requests)
			),
			frappe.ValidationError,
		)


def block_rename_for_open_request(doc, method=None, old=None, new=None, merge=False) -> None:
	"""before_rename: a renamed (or merged) record would slip out from under the delete guard

	Allowed only inside the erasure job of a request that references the record: the job renames
	her Contact and Address, whose names spell her name (`crm.erasure.record_renames`).
	"""
	requests = requests_referencing(doc.doctype, [old or doc.name], OPEN_STATES)
	running = frappe.flags.get(ERASURE_EXECUTION_FLAG)
	if requests and not (running and running in requests and not merge):
		frappe.throw(
			_("{0} {1} cannot be renamed while erasure request {2} is open").format(
				_(doc.doctype), old or doc.name, ", ".join(requests)
			),
			frappe.ValidationError,
		)


def follow_rename(doc, method=None, old=None, new=None, merge=False) -> None:
	"""after_rename: only decided requests can reference the old name here (open ones block above)"""
	if old and new and old != new and has_requests_in(list(ALL_STATES)):  # False before the table exists
		rewrite_references(doc.doctype, old, new)
