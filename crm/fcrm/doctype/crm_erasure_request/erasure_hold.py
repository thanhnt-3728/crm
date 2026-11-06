# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
"""Hold rule: a request waits On Hold while its subject sits on an open deal (deadlines keep running)"""

import operator
from collections.abc import Iterable
from functools import reduce

import frappe
from frappe.query_builder.functions import Coalesce

from crm.fcrm.doctype.crm_erasure_request.erasure_request_references import (
	REQUEST,
	has_requests_in,
	requests_referencing,
	subject_refs,
)
from crm.fcrm.doctype.crm_erasure_request.erasure_states import HOLD_STATES, ON_HOLD, PENDING_APPROVAL

CLOSED_DEAL_TYPES = ("Won", "Lost")


def blocking_open_deals(request, ignore_deals: Iterable[str] = ()) -> list[str]:
	"""Sorted names of open deals (status type not Won/Lost) tied to the request's subject

	A deal is tied when it is the source or a match, its `lead` is her lead, or her contact is
	its `contact` or one of its `CRM Contacts` rows. Excluded matches do not count, nor do
	`ignore_deals` (a deal being deleted).
	"""
	refs = subject_refs(request)
	deal, status = frappe.qb.DocType("CRM Deal"), frappe.qb.DocType("CRM Deal Status")
	conditions = []
	if refs["CRM Deal"]:
		conditions.append(deal.name.isin(sorted(refs["CRM Deal"])))
	if refs["CRM Lead"]:
		conditions.append(deal.lead.isin(sorted(refs["CRM Lead"])))
	if refs["Contact"]:
		contacts = sorted(refs["Contact"])
		deal_contact = frappe.qb.DocType("CRM Contacts")
		rows = (
			frappe.qb.from_(deal_contact)
			.select(deal_contact.parent)
			.where(deal_contact.parenttype == "CRM Deal")
			.where(deal_contact.contact.isin(contacts))
		)
		conditions += [deal.contact.isin(contacts), deal.name.isin(rows)]
	if not conditions:
		return []

	query = (
		frappe.qb.from_(deal)
		.left_join(status)
		.on(status.name == deal.status)
		.select(deal.name)
		.where(reduce(operator.or_, conditions))
		# a deal with a missing status counts as open: holding is the safe side
		.where(Coalesce(status.type, "").notin(CLOSED_DEAL_TYPES))
		.orderby(deal.name)
	)
	if ignore_deals:
		query = query.where(deal.name.notin(sorted(ignore_deals)))
	return query.run(pluck=True)


def refresh_hold(request, ignore_deals: Iterable[str] = ()) -> list[str]:
	"""Move a Pending Approval / On Hold request to the state its open deals call for

	Returns the blocking deal names. Draft and decided requests are left as they are.
	Callers that can race a deal save (the deal hooks, phase 03 approve) load `request` with
	`frappe.get_doc(..., for_update=True)` first so the row lock serializes the writes.
	"""
	if request.status not in HOLD_STATES:
		return []
	deals = blocking_open_deals(request, ignore_deals)
	reason = format_hold_reason(deals)
	if request.status == PENDING_APPROVAL and deals:
		request.transition_to(ON_HOLD, hold_reason=reason)
	elif request.status == ON_HOLD and not deals:
		request.transition_to(PENDING_APPROVAL, hold_reason=None)
	elif request.status == ON_HOLD and (request.hold_reason or "") != reason:
		request.save_system_fields(hold_reason=reason)
	return deals


def format_hold_reason(deals: list[str]) -> str:
	"""Deal names only: the hold reason never carries personal data"""
	return ", ".join(deals)


def on_deal_update(doc, method=None):
	"""CRM Deal on_update: re-run the hold rule for requests whose subject this deal touches"""
	_refresh_requests_touching(doc)


def on_deal_trash(doc, method=None):
	"""CRM Deal on_trash: a deleted deal no longer holds anyone (it ran after the delete guard)"""
	_refresh_requests_touching(doc, ignore_deals={doc.name})


def _refresh_requests_touching(doc, ignore_deals: Iterable[str] = ()):
	if not has_requests_in(list(HOLD_STATES)):
		return
	refs = _deal_person_refs(doc)
	before = doc.get_doc_before_save()
	if before:
		for doctype, names in _deal_person_refs(before).items():
			refs[doctype] |= names

	requests = set()
	for doctype, names in refs.items():
		requests.update(requests_referencing(doctype, names, HOLD_STATES, skip_existence_check=True))
	for name in sorted(requests):
		refresh_hold(frappe.get_doc(REQUEST, name, for_update=True), ignore_deals)


def _deal_person_refs(deal) -> dict[str, set[str]]:
	contacts = {row.contact for row in deal.get("contacts") or [] if row.contact}
	if deal.get("contact"):
		contacts.add(deal.contact)
	return {
		"CRM Deal": {deal.name},
		"CRM Lead": {deal.lead} if deal.get("lead") else set(),
		"Contact": contacts,
	}
