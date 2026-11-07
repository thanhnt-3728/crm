# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Who sees and writes a CRM Erasure Request (design 5.1), and what each user may do with it.

* Compliance (an explicit `Has Role` row) and Sales Managers read every request.
* Everyone else sees a request only while they logged it and it is still Logged. Once submitted, the
  document is denied outright, so no generic endpoint (`frappe.client.get`, `get_list` with every
  field) can show its identifiers. The logger sees status and due dates only through `list_requests`.
* Writes: Compliance any request; Sales Managers and Sales Users only their own Logged request.

Decisions read the stored status and logger, never the in-memory document, which a crafted
`frappe.client.save` payload controls.
"""

import frappe
from frappe import _
from frappe.utils import date_diff, getdate, today

from crm.privacy.request_status import (
	AWAITING,
	CLOSED,
	DECLINED,
	EDITABLE_STATUSES,
	ERASED,
	FROZEN_JOB_STATUSES,
	LOGGED,
	ON_HOLD,
)
from crm.privacy.roles import COMPLIANCE_ROLE, has_explicit_role

DOCTYPE = "CRM Erasure Request"
READ_PTYPES = ("read", "select")
# Never sent to the browser: the plan hash is checked server-side, the deletion list holds file URLs.
INTERNAL_FIELDS = ("approved_plan_hash", "pending_file_deletions")
SUBMITTED_ROW_KEYS = ("name", "status", "acknowledge_by", "respond_by", "days_left")


def is_compliance(user: str | None) -> bool:
	return has_explicit_role(user, COMPLIANCE_ROLE)


def sees_all(user: str) -> bool:
	return user == "Administrator" or is_compliance(user) or "Sales Manager" in frappe.get_roles(user)


def has_permission(doc, ptype: str, user: str | None = None) -> bool:
	"""Hook for `has_permission`. A controller can only deny, so it always returns an explicit bool."""
	user = user or frappe.session.user
	if user == "Administrator" or ptype == "create" or is_compliance(user):
		return True
	stored = (
		frappe.db.get_value(DOCTYPE, doc.name, ["status", "logged_by"], as_dict=True) if doc.name else None
	)
	if not stored:
		return True  # not saved yet: nothing to protect
	if ptype in READ_PTYPES and sees_all(user):
		return True
	return stored.logged_by == user and stored.status == LOGGED


def _own_logged_condition(user: str) -> str:
	return (
		f"`tab{DOCTYPE}`.`logged_by` = {frappe.db.escape(user)} "
		f"and `tab{DOCTYPE}`.`status` = {frappe.db.escape(LOGGED)}"
	)


def get_permission_query_conditions(user: str | None = None, doctype: str | None = None) -> str:
	user = user or frappe.session.user
	return "" if sees_all(user) else f"({_own_logged_condition(user)})"


def trim_for_user(row: dict, full_access: bool) -> frappe._dict:
	"""A list row as the user may see it: everything but the internal fields while the request is Logged
	or when they see all requests, else only the status and due dates. `row` already carries days_left."""
	if full_access or row["status"] == LOGGED:
		return frappe._dict({key: value for key, value in row.items() if key not in INTERNAL_FIELDS})
	return frappe._dict({key: row[key] for key in SUBMITTED_ROW_KEYS})


def days_left(respond_by) -> int | None:
	"""Calendar days until the response is due; negative once overdue."""
	return date_diff(getdate(respond_by), getdate(today())) if respond_by else None


def available_actions(doc, user: str) -> dict[str, bool]:
	"""Action flags for `get_request`. Role and state only: each API still enforces its own check."""
	frozen = doc.erasure_job_status in FROZEN_JOB_STATUSES
	compliance = is_compliance(user)
	status = doc.status
	open_ = not frozen and status != CLOSED
	return {
		"edit": not frozen and status in EDITABLE_STATUSES and doc.has_permission("write", user=user),
		"submit": not frozen and status == LOGGED and (compliance or doc.logged_by == user),
		"approve": not frozen and compliance and status == AWAITING,
		"decline": not frozen and compliance and status in (LOGGED, AWAITING, ON_HOLD),
		"close": not frozen and compliance and status in (ERASED, DECLINED),
		"manage_checklist": open_ and compliance,
		"mark_acknowledged": open_ and compliance and not doc.acknowledgment_sent,
		"recheck_hold": not frozen and compliance and status in (AWAITING, ON_HOLD),
		# what `set_contract_references` enforces: Compliance, before the erasure, not while the job runs
		"set_contract_references": not frozen and compliance and status in EDITABLE_STATUSES,
	}


def refuse_share(doc, method=None) -> None:
	"""`doc_events` hook on DocShare. A share bypasses `has_permission` and the query conditions, so it
	would show a request in full to anyone: refuse it for every user, Administrator included. Assigning
	a request creates a share, so it fails the same way."""
	if doc.share_doctype == DOCTYPE:
		frappe.throw(_("Erasure requests can't be shared or assigned; access follows the Compliance role"))
