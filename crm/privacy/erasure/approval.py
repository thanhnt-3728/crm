# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Approving, declining and preparing an erasure request (phase 05; RT-1, RT-2; design 5.6, 5.11).

Every function checks the caller itself, on the server, by an explicit Compliance row (`Administrator` alone is
refused) and by user id for the approver, then writes inside `server_write()`. Approval stops at the enqueue:
the job is `crm.privacy.erasure.executor.run`.
"""

import frappe
from frappe import _
from frappe.utils import now_datetime

from crm.privacy.erasure.plan import ErasureHoldError
from crm.privacy.erasure.plan_builder import build_plan
from crm.privacy.erasure.preview import build_preview
from crm.privacy.on_hold import dispatch, evaluate_hold
from crm.privacy.request_status import (
	AWAITING,
	DECLINED,
	EDITABLE_STATUSES,
	ON_HOLD,
	assert_not_frozen,
	server_write,
)
from crm.privacy.request_visibility import DOCTYPE, is_compliance

JOB = "crm.privacy.erasure.executor.run"
JOB_TIMEOUT = 3600
REFERENCE_LENGTH = 140


def require_compliance(user: str, action: str) -> None:
	if not is_compliance(user):
		frappe.throw(_("Only Compliance can {0} an erasure request").format(action), frappe.PermissionError)


def load(name: str):
	"""The request, locked so two clicks on Approve cannot both pass the checks."""
	frappe.db.get_value(DOCTYPE, name, "name", for_update=True)
	return frappe.get_doc(DOCTYPE, name)


def assert_editable(doc) -> None:
	"""Only a request that has not been erased or declined can still change."""
	if doc.status not in EDITABLE_STATUSES:
		frappe.throw(_("A request that is {0} can no longer be changed").format(_(doc.status)))


def preview(name: str, user: str) -> dict:
	"""What approving this request would remove and keep (see `crm.privacy.erasure.preview`)."""
	require_compliance(user, _("review"))
	doc = frappe.get_doc(DOCTYPE, name)
	assert_editable(doc)
	return build_preview(doc)


def assert_can_approve(doc, user: str, typed_number: str | None) -> None:
	if (doc.logged_by or "").lower() == user.lower():
		frappe.throw(
			_("You logged this request, so you cannot approve your own request"), frappe.PermissionError
		)
	assert_not_frozen(doc.erasure_job_status)
	if doc.status == ON_HOLD:
		frappe.throw(_("The request is On Hold: an open deal still lists the person"))
	if doc.status != AWAITING:
		frappe.throw(_("Only a request that is Awaiting sign-off can be approved"))
	if (typed_number or "").strip() != doc.name:
		frappe.throw(_("Type the request number to confirm"))
	retention = frappe.db.get_single_value("CRM Privacy Settings", "contract_retention_months") or 0
	if doc.contract_references and retention <= 0:
		frappe.throw(_("Set the contract retention period in the privacy settings before approving"))


def hold_again(doc) -> bool:
	"""Re-run the hold check at the moment of approval (RT-2). True when the request went (back) On Hold."""
	dispatch(evaluate_hold(doc))
	return doc.status == ON_HOLD


def approve(name: str, typed_number: str | None, user: str):
	"""Check, freeze what is about to run and enqueue the job. Returns the request; if a deal now holds it the
	request is On Hold and nothing is queued (the caller gets the new status, not an error: an error would roll
	back the status change)."""
	require_compliance(user, _("approve"))
	doc = load(name)
	assert_can_approve(doc, user, typed_number)
	if hold_again(doc):
		return doc
	try:
		plan = build_plan(doc)
	except ErasureHoldError:
		if not hold_again(doc):
			raise
		return doc
	now = now_datetime()
	with server_write():
		doc.update(
			{
				"approver": user,
				"approved_on": now,
				"erasure_job_status": "Queued",
				"erasure_queued_at": now,
				"erasure_error": None,
				"approved_plan_hash": plan.hash(),
			}
		)
		doc.save(ignore_permissions=True)
	frappe.enqueue(
		JOB,
		queue="long",
		timeout=JOB_TIMEOUT,
		job_id=f"erasure::{name}",
		deduplicate=True,
		enqueue_after_commit=True,
		request=name,
	)
	return doc


def decline(name: str, reason: str | None, user: str):
	require_compliance(user, _("decline"))
	if not (reason or "").strip():
		frappe.throw(_("A reason is required to decline a request"))
	doc = load(name)
	assert_not_frozen(doc.erasure_job_status)
	assert_editable(doc)
	with server_write():
		doc.status = DECLINED
		doc.denial_reason = reason.strip()
		doc.save(ignore_permissions=True)
	return doc


def set_references(name: str, references: list, user: str):
	"""Replace the contract references (design 5.11): blanks dropped, repeats kept once."""
	require_compliance(user, _("edit"))
	if not isinstance(references, list) or not all(isinstance(r, str) for r in references):
		frappe.throw(_("references must be a list of text"))
	doc = load(name)
	assert_not_frozen(doc.erasure_job_status)
	assert_editable(doc)
	cleaned = list(dict.fromkeys(r.strip() for r in references if r.strip()))
	if any(len(r) > REFERENCE_LENGTH for r in cleaned):
		frappe.throw(_("A contract reference can have at most {0} characters").format(REFERENCE_LENGTH))
	doc.set("contract_references", [{"reference": r} for r in cleaned])
	with server_write():
		doc.save(ignore_permissions=True)
	return doc
