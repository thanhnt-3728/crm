# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""On Hold: which open deals keep a request from sign-off, and every way out of that state (design 5.2).

An open deal holds a request when it lists a confirmed Contact or is itself a confirmed match (RT-2), recomputed
from the records each time. A hook (RT-11) does one cheap lookup and queues a per-request job after the commit (M1);
whatever can fail runs isolated: savepoint, no message for the user (M2), PDR number and class name logged (V1).
"""

from contextlib import contextmanager

import frappe
from frappe import _

from crm.privacy import notify
from crm.privacy.error_log import log_privacy_error
from crm.privacy.hold_rows import DEAL, HOLD, sync_rows
from crm.privacy.request_status import AWAITING, FROZEN_JOB_STATUSES, LOGGED, ON_HOLD, server_write
from crm.privacy.request_visibility import DOCTYPE

CONTACT = "Contact"
OPEN_TYPES = ("Open", "Ongoing", "On Hold")
SAVEPOINT = "erasure_hold_recheck"
RECHECK = "crm.privacy.on_hold.recheck_request"


def is_open_deal(deal: str) -> bool:
	"""A deal is open when its status maps to a CRM Deal Status of type Open, Ongoing or On Hold."""
	status = frappe.db.get_value(DEAL, deal, "status")
	return bool(status) and frappe.db.get_value("CRM Deal Status", status, "type") in OPEN_TYPES


def _facts(doc) -> frappe._dict:
	"""Deals that list a confirmed contact (`listing`), deals confirmed as matches (`confirmed`) and `state`, a map
	of those and of the "Hold deal" rows' deals that still exist to `{open, owner}`. Deleted records are absent."""
	rows = [(r.reference_doctype, r.reference_name) for r in doc.matches if r.confirmed]
	wanted = [name for doctype, name in rows if doctype == CONTACT]
	contacts = frappe.get_all(CONTACT, {"name": ["in", wanted]}, pluck="name") if wanted else []
	listing = set()
	if contacts:
		Contacts = frappe.qb.DocType("CRM Contacts")
		query = frappe.qb.from_(Contacts).select(Contacts.parent)
		listing = set(
			query.where(Contacts.contact.isin(contacts) & (Contacts.parenttype == DEAL)).run(pluck=True)
		)
	confirmed = {name for doctype, name in rows if doctype == DEAL}
	holding = {r.reference_name for r in doc.matches if r.reference_doctype == DEAL and r.relation == HOLD}
	names = list(listing | confirmed | holding)
	open_statuses = set(frappe.get_all("CRM Deal Status", {"type": ["in", OPEN_TYPES]}, pluck="name"))
	deals = frappe.get_all(DEAL, {"name": ["in", names]}, ["name", "status", "deal_owner"]) if names else []
	state = {d.name: frappe._dict(open=d.status in open_statuses, owner=d.deal_owner) for d in deals}
	return frappe._dict(listing=listing & state.keys(), confirmed=confirmed & state.keys(), state=state)


def holding_owners(doc) -> dict[str, str | None]:
	"""The open deals that hold the request right now, each with its owner (a User name or None)."""
	facts = _facts(doc)
	return {d: facts.state[d].owner for d in facts.listing | facts.confirmed if facts.state[d].open}


def add_owner_names(doc, data: dict) -> None:
	"""While On Hold, `owner_name` (staff data, not the requester's) on the match rows of the open deals that hold
	the request. The caller runs this before `hide_unreadable`, so a row the viewer cannot read leaves with its name."""
	if doc.status != ON_HOLD:
		return
	owners = holding_owners(doc)
	for match in data["matches"]:
		owner = owners.get(match.reference_name) if match.reference_doctype == "CRM Deal" else None
		if owner:
			match["owner_name"] = frappe.db.get_value("User", owner, "full_name") or owner


def evaluate_hold(doc, *, submit: bool = False, frozen_ok: bool = False) -> frappe._dict:
	"""Recompute the hold of a request that is Awaiting sign-off or On Hold (or Logged when `submit`), update its
	match rows and status, and save. Returns `{request, status, held, notices, awaiting}`: `notices` are [deal, owner,
	why] for held deals whose owner has no notice yet; pass it to `dispatch`. `frozen_ok` is for the executor."""
	result = frappe._dict(request=doc.name, status=doc.status, held=[], notices=[], awaiting=False)
	if doc.status not in (AWAITING, ON_HOLD) and not (submit and doc.status == LOGGED):
		return result
	facts = _facts(doc)
	source = {r.reference_name for r in doc.matches if r.is_source and r.reference_doctype == DEAL}
	kinds = [
		(facts.listing, notify.CONTACT_HOLD),
		(source, notify.SOURCE_HOLD),
		(facts.confirmed, notify.CONFIRMED_HOLD),
	]
	held = {
		d: next(kind for group, kind in kinds if d in group)
		for d in facts.listing | facts.confirmed
		if facts.state[d].open
	}
	with server_write(frozen_ok=frozen_ok):
		changed = sync_rows(doc, facts, held)
		target = ON_HOLD if held else AWAITING
		moved = target != doc.status
		if moved:
			doc.status = target
		if changed or moved:
			doc.save(ignore_permissions=True)
	notices = [
		[deal, facts.state[deal].owner, why]
		for deal, why in held.items()
		if facts.state[deal].owner and not notify.has_hold_notice(doc.name, deal, facts.state[deal].owner)
	]
	result.update(status=doc.status, held=list(held), notices=notices, awaiting=moved and target == AWAITING)
	return result


def dispatch(result) -> None:
	"""Send the notices `evaluate_hold` asked for."""
	if result.notices or result.awaiting:
		notify.deliver_hold_notices(result.request, result.notices, result.awaiting)


def requests_holding(doctype: str, name: str) -> list[str]:
	"""On Hold requests with a match row for this deal or contact."""
	Match, Request = frappe.qb.DocType("CRM Erasure Match"), frappe.qb.DocType(DOCTYPE)
	query = (
		frappe.qb.from_(Match)
		.join(Request)
		.on(Match.parent == Request.name)
		.select(Request.name)
		.where((Match.parenttype == DOCTYPE) & (Request.status == ON_HOLD))
		.where((Match.reference_doctype == doctype) & (Match.reference_name == name))
	)
	return query.distinct().run(pluck=True)


@contextmanager
def _isolated(title: str, request: str | None = None):
	"""Run a block that must never break or alarm the user's write: on error roll back to a savepoint, drop the
	messages it queued (a red dialog naming the PDR) and log the PDR number and exception class only (V1)."""
	queued = len(frappe.local.message_log)
	failed = None
	try:
		frappe.db.savepoint(SAVEPOINT)
		yield
	except Exception as error:
		frappe.db.rollback(save_point=SAVEPOINT)
		del frappe.local.message_log[queued:]
		failed = type(error).__name__
	if failed:  # outside the handler, with neutral metadata: the request's form data holds personal data
		log_privacy_error(title, failed, reference_doctype=DOCTYPE, reference_name=request)


def recheck_request(request: str) -> None:
	"""The job: re-evaluate one On Hold request that is not frozen. It takes the request row lock first, so runs queue
	up and the later one sees the earlier one's commit, then loads the request fresh. Safe to run twice."""
	with _isolated(request, request):
		frappe.db.get_value(DOCTYPE, request, "name", for_update=True)
		doc = frappe.get_doc(DOCTYPE, request)
		if doc.status == ON_HOLD and doc.erasure_job_status not in FROZEN_JOB_STATUSES:
			dispatch(evaluate_hold(doc))


def _queue_rechecks(doctype: str, name: str) -> None:
	"""A hook's only work: find the On Hold requests that mention this record and queue one deduplicated job each,
	after the user's transaction commits. The hook never reads or writes a request."""
	with _isolated(f"{doctype} hold re-check"):
		if not frappe.db.exists(DOCTYPE, {"status": ON_HOLD}):  # the cheap bail-out: nothing to look up
			return
		for request in requests_holding(doctype, name):
			frappe.enqueue(
				RECHECK,
				queue="short",
				enqueue_after_commit=True,
				job_id=f"erasure-hold-recheck::{request}",
				deduplicate=True,
				request=request,
			)


def recheck_for_deal(doc, method=None) -> None:
	"""`CRM Deal` on_update and on_trash: the deal may now be Won/Lost, have lost the person, or be gone."""
	_queue_rechecks(DEAL, doc.name)


def recheck_for_contact(doc, method=None) -> None:
	"""`Contact` on_trash: deals listing a contact that is going away stop holding the request."""
	_queue_rechecks(CONTACT, doc.name)


def recheck_all_on_hold() -> None:
	"""Daily: catches whatever the hooks missed (raw writes, imports, a failed hook or job)."""
	for request in frappe.get_all(DOCTYPE, {"status": ON_HOLD}, pluck="name"):
		recheck_request(request)
