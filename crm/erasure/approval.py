# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
"""Approval endpoints (F1-F3), exposed as `crm.api.erasure.<name>`; POST only, typed

- get_approval_preview(name): a decider re-runs discovery; `preview()` payload plus `preview_hash`
  (sha256 of every match key, readable or not, so a change the approver cannot see still counts)
- approve(name, confirm_name, excluded, preview_hash): two-person rule, exact typed request
  number, hold re-check (-> On Hold, committed, then throws), stale preview -> ErasurePreviewStale,
  final matches and exclusions stored, Approved, job queued after commit
- reject(name, reason) by a decider; close(name) and retry_execution(name) by any Privacy Officer

Exclusions are planned exactly as `set_exclusions` plans them (`match_rows.plan_exclusions`): the
approver's `excluded` keys must be matches they can read, keys of rows excluded only through a
parent are ignored, and stored exclusions on rows they cannot read are kept.
"""

import hashlib

import frappe
from frappe import _
from frappe.utils import now_datetime

from crm.erasure.discovery import discover
from crm.erasure.jobs import enqueue_execution
from crm.erasure.match_rows import VIA_EXCLUDED, format_key, hand_excluded, match_key, parse_key, plan_exclusions
from crm.erasure.preview import preview, readable_keys
from crm.erasure.retention import apply_retention
from crm.fcrm.doctype.crm_erasure_request.erasure_guards import assert_can_decide
from crm.fcrm.doctype.crm_erasure_request.erasure_hold import blocking_open_deals, format_hold_reason, refresh_hold
from crm.fcrm.doctype.crm_erasure_request.erasure_states import (
	APPROVED,
	CLOSED,
	HOLD_STATES,
	ON_HOLD,
	PENDING_APPROVAL,
	PRIVACY_OFFICER_ROLE,
	REJECTED,
)

REQUEST = "CRM Erasure Request"
STALE_MESSAGE = "Matches changed, reload the preview"


class ErasurePreviewStale(frappe.ValidationError):
	"""The matches differ from the preview the approver confirmed (`exc_type` for the UI)"""


@frappe.whitelist(methods=["POST"])
def get_approval_preview(name: str) -> dict:
	request = _load(name)
	assert_can_decide(request)
	if request.status not in HOLD_STATES:
		frappe.throw(_("{0} is not waiting for approval").format(request.name))
	rows, _reachable, aware = _replan(request, hand_excluded(request.matches))
	payload = preview(_view(request, rows), aware.hidden)
	payload["preview_hash"] = matches_hash(rows)
	return payload


@frappe.whitelist(methods=["POST"])
def approve(name: str, confirm_name: str, excluded: list[str], preview_hash: str) -> dict:
	request = _load(name, for_update=True)  # a second approve waits here, then sees Approved
	assert_can_decide(request)
	if request.status != PENDING_APPROVAL:
		frappe.throw(_("{0} is {1}, not Pending Approval").format(request.name, _(request.status)))
	if (confirm_name or "").strip() != request.name:
		frappe.throw(_("Type the request number {0} exactly to approve").format(request.name))
	if refresh_hold(request):
		_hold_and_throw(request)
	stored_hand = hand_excluded(request.matches)
	rows, reachable, aware = _replan(request, stored_hand)
	if matches_hash(rows) != preview_hash:
		frappe.throw(_(STALE_MESSAGE), ErasurePreviewStale)
	hand = _final_exclusions(request, rows, excluded)
	if hand != stored_hand:
		aware = _discover(request, hand)
	final = plan_exclusions(rows, hand, reachable.matches, aware.matches)
	request.replace_matches(final)
	deals = blocking_open_deals(request)  # re-discovery may have found an open deal of hers
	if deals:
		request.transition_to(ON_HOLD, hold_reason=format_hold_reason(deals))
		_hold_and_throw(request)
	request.transition_to(APPROVED, approver=frappe.session.user, approved_on=now_datetime())
	enqueue_execution(request.name)
	return {"name": request.name, "status": request.status}


@frappe.whitelist(methods=["POST"])
def reject(name: str, reason: str) -> dict:
	request = _load(name, for_update=True)
	reason = (reason or "").strip()
	if not reason:
		frappe.throw(_("Give a reason for rejecting {0}").format(request.name))
	request.transition_to(REJECTED, rejection_reason=reason)  # decider, from Draft/Pending/On Hold
	apply_retention(request)  # a rejected request keeps no more of her than a closed one
	return {"name": request.name, "status": request.status}


@frappe.whitelist(methods=["POST"])
def close(name: str) -> dict:
	_assert_privacy_officer()
	request = _load(name, for_update=True)
	request.transition_to(CLOSED)  # legal from Executed only
	apply_retention(request)
	return {"name": request.name, "status": request.status}


@frappe.whitelist(methods=["POST"])
def retry_execution(name: str) -> dict:
	_assert_privacy_officer()
	request = _load(name, for_update=True)
	if request.status != APPROVED:
		frappe.throw(_("Only an Approved request can be run again; {0} is {1}").format(name, _(request.status)))
	enqueue_execution(request.name)
	return {"name": request.name, "status": request.status}


def _hold_and_throw(request) -> None:
	# Commit, then throw: the request must stay On Hold (and keep its re-discovered matches), but the
	# approver must see an error, and the throw rolls back whatever is not committed yet.
	frappe.db.commit()
	frappe.throw(_("{0} is On Hold while deals {1} are open").format(request.name, request.hold_reason))


def matches_hash(rows) -> str:
	"""`preview_hash`: sha256 of the sorted "<doctype>::<name>" keys of every match row"""
	keys = sorted(format_key(*match_key(row)) for row in rows)
	return hashlib.sha256("\n".join(keys).encode()).hexdigest()


def _replan(request, hand: set):
	"""Rows after re-discovery with `hand` exclusions, as `set_exclusions` plans them"""
	reachable, aware = _discover(request, set()), _discover(request, hand)
	return plan_exclusions(request.matches, hand, reachable.matches, aware.matches), reachable, aware


def _final_exclusions(request, rows: list[dict], excluded: list[str] | None) -> set:
	try:
		keys = {parse_key(key) for key in excluded or []}
	except ValueError:
		keys = None
	readable = readable_keys(_view(request, rows))
	if keys is None or not keys <= readable:
		frappe.throw(_("One of the excluded keys is not a match of {0}").format(request.name))
	via_parent = {match_key(row) for row in rows if row.get("reason") == VIA_EXCLUDED}
	return (keys - via_parent) | (hand_excluded(rows) - readable)


def _view(request, rows: list[dict]) -> frappe._dict:
	"""The request with `rows` as its matches, for `preview()` (nothing is saved)"""
	fields = ("name", "status", "hold_reason", "ack_due", "response_due", "modified")
	view = frappe._dict({field: request.get(field) for field in (*fields, "source_doctype", "source_docname")})
	view.update(identifiers=request.identifiers, matches=[frappe._dict(row) for row in rows])
	return view


def _load(name: str, for_update: bool = False):
	if not name or not frappe.db.exists(REQUEST, name):
		frappe.throw(_("Erasure request {0} not found").format(name), frappe.DoesNotExistError)
	return frappe.get_doc(REQUEST, name, for_update=for_update)


def _assert_privacy_officer() -> None:
	if PRIVACY_OFFICER_ROLE not in frappe.get_roles(frappe.session.user):
		frappe.throw(_("Only a Privacy Officer can do this"), frappe.PermissionError)


def _discover(request, excluded: set):
	try:
		return discover(request, excluded)
	except ValueError:  # a stored identifier no longer normalizes; never echo it
		frappe.throw(_("An identifier stored on {0} is not valid; correct the request").format(request.name))
