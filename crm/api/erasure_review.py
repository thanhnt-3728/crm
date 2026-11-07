# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Compliance actions on an erasure request: preview, approve, decline, contract references (phase 05).

Each function is a thin wrapper: the rules, the Compliance check and the writes live in
`crm.privacy.erasure.approval`, so the checks are on the server whatever calls them.
"""

import frappe

from crm.api.erasure_requests import request_response
from crm.privacy import compliance_members, request_checklist, request_close
from crm.privacy.erasure import approval


@frappe.whitelist()
def approve_request(name: str, typed_number: str) -> dict:
	"""Approve and enqueue the erasure. `typed_number` must be the request number. A deal that now lists the
	person puts the request On Hold instead (the response then shows status On Hold and nothing is queued)."""
	return request_response(approval.approve(name, typed_number, frappe.session.user))


@frappe.whitelist()
def decline_request(name: str, reason: str) -> dict:
	"""Decline a request that is not being erased. The reason is required."""
	return request_response(approval.decline(name, reason, frappe.session.user))


@frappe.whitelist()
def set_contract_references(name: str, references: list) -> dict:
	"""Replace the signed-contract references (design 5.11) before approval. Not while the job runs."""
	return request_response(approval.set_references(name, references, frappe.session.user))


@frappe.whitelist()
def get_erasure_preview(name: str) -> dict:
	"""Compliance only: what approving would remove and keep, the open checklist items, custom fields off the
	personal-fields list, per-identifier hit counts and what needs a human look. See `crm.privacy.erasure.preview`."""
	return approval.preview(name, frappe.session.user)


@frappe.whitelist()
def add_checklist_item(name: str, description: str | None) -> dict:
	"""Add an item for a copy of the data outside the CRM (design 5.7). Compliance only, until the request is closed."""
	return request_response(request_checklist.add_item(name, description, frappe.session.user))


@frappe.whitelist()
def set_checklist_item_done(name: str, row: str, done: bool) -> dict:
	"""Tick or untick one checklist item by its row name. A tick records who and when. Compliance only."""
	return request_response(request_checklist.set_done(name, row, done, frappe.session.user))


@frappe.whitelist()
def mark_acknowledged(name: str, acknowledged_on: str | None = None) -> dict:
	"""Record that the requester was acknowledged (today when no date is given). Compliance only."""
	return request_response(request_checklist.acknowledge(name, acknowledged_on, frappe.session.user))


@frappe.whitelist()
def close_request(
	name: str, date_answered: str | None, outcome: str | None, denial_reason: str | None = None
) -> dict:
	"""Record the answer and close an Erased or Declined request: every checklist item must be done, and Denied or
	Partly completed needs a reason. This wipes the requester's details and the emails and files attached to the
	request; only the log entry stays, for 24 months. Compliance only."""
	return request_response(
		request_close.close(name, date_answered, outcome, denial_reason, frappe.session.user)
	)


@frappe.whitelist()
def set_compliance_member(user: str, enabled: bool) -> list[dict]:
	"""System Manager only: give a user the Compliance role (an explicit Has Role row) or take it away. Refuses the
	caller's own user, so nobody makes themselves an approver, and audits each change with a Comment on the privacy
	settings. Returns the current members."""
	return compliance_members.set_member(user, frappe.parse_json(enabled), frappe.session.user)
