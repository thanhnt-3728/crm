# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Before the job touches anything (RT-1, RT-2): claim it, then check the approver, the secret, the hold and the
plan hash inside the locked transaction."""

import frappe
from frappe import _
from frappe.utils import now_datetime

from crm.fcrm.doctype.crm_privacy_settings.crm_privacy_settings import get_dnc_secret
from crm.privacy.erasure.executor_outcomes import (
	APPROVER_LOST,
	OPEN_DEAL,
	PLAN_CHANGED,
	BackOnHold,
	Refused,
	release_to_hold,
)
from crm.privacy.erasure.plan import ErasureHoldError, ErasurePlan
from crm.privacy.erasure.plan_builder import build_plan
from crm.privacy.on_hold import dispatch, evaluate_hold
from crm.privacy.request_status import AWAITING, ON_HOLD
from crm.privacy.request_visibility import DOCTYPE
from crm.privacy.roles import COMPLIANCE_ROLE, has_explicit_role


def claim(request: str) -> bool:
	"""Compare-and-set Queued -> Running (RT-1): read the row under its lock, and take it only if it is still
	Queued and approved. Otherwise another worker has it or it is no longer approved: exit. Commits only this."""
	row = frappe.db.get_value(
		DOCTYPE, request, ["status", "erasure_job_status"], as_dict=True, for_update=True
	)
	claimed = bool(row) and row.status == AWAITING and row.erasure_job_status == "Queued"
	if claimed:
		frappe.db.set_value(
			DOCTYPE,
			request,
			{"erasure_job_status": "Running", "erasure_started_at": now_datetime()},
			update_modified=False,
		)
	frappe.db.commit()
	return claimed


def load_locked(request: str):
	frappe.db.get_value(DOCTYPE, request, "name", for_update=True)
	return frappe.get_doc(DOCTYPE, request)


def check_approver(doc) -> None:
	approver = doc.approver or ""
	if not has_explicit_role(approver, COMPLIANCE_ROLE) or approver.lower() == (doc.logged_by or "").lower():
		raise Refused(_(APPROVER_LOST))


def preflight(doc) -> ErasurePlan:
	"""Inside the locked transaction: approver, secret, hold, then the plan against the approved hash."""
	check_approver(doc)
	get_dnc_secret()  # raises when the key is lost while entries exist: fail before erasing anything
	result = evaluate_hold(doc, frozen_ok=True)
	dispatch(result)
	if doc.status == ON_HOLD:
		release_to_hold(doc)
		raise BackOnHold
	try:
		plan = build_plan(doc)
	except ErasureHoldError:
		raise Refused(_(OPEN_DEAL)) from None
	if plan.hash() != doc.approved_plan_hash:
		# stored untranslated on purpose: the UI recognises this failure by its English text and shows its own banner
		raise Refused(PLAN_CHANGED)
	return plan
