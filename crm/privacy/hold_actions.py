# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The submit and re-check actions behind `submit_request` and `recheck_hold` (design 5.2).

The API functions check who may call; these run the rules and the hold evaluation.
"""

import frappe
from frappe import _

from crm.privacy.on_hold import dispatch, evaluate_hold
from crm.privacy.request_status import AWAITING, LOGGED, ON_HOLD, assert_not_frozen
from crm.privacy.request_visibility import days_left, is_compliance, trim_for_user


def submit(doc) -> None:
	"""Move a Logged request on: it needs a confirmed match and a kept identifier. It becomes On Hold when an
	open deal still lists the person or is confirmed, else Awaiting sign-off, and the notices go out."""
	if doc.status != LOGGED:
		frappe.throw(_("Only a Logged request can be submitted"))
	if not any(m.confirmed for m in doc.matches):
		frappe.throw(_("Confirm at least one matching record before submitting"))
	if all(i.excluded for i in doc.identifiers):
		frappe.throw(_("Keep at least one identifier before submitting"))
	dispatch(evaluate_hold(doc, submit=True))


def submitted_row(doc) -> dict:
	"""What the logger may see of a request once it is submitted: status and due dates."""
	row = doc.as_dict()
	row["days_left"] = days_left(doc.respond_by)
	return dict(trim_for_user(row, False))


def recheck(doc, user: str) -> None:
	"""Compliance only: look at the open deals again now, for a request that is Awaiting sign-off or On Hold."""
	if not is_compliance(user):
		frappe.throw(_("Only Compliance can re-check the hold"), frappe.PermissionError)
	assert_not_frozen(doc.erasure_job_status)
	if doc.status not in (AWAITING, ON_HOLD):
		frappe.throw(_("Only a request that is Awaiting sign-off or On Hold can be re-checked"))
	dispatch(evaluate_hold(doc))
