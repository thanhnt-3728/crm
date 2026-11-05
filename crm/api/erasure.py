"""Whitelisted endpoints of the erasure-request feature (spec 5.1 - 5.8).

The server is the authority for every rule here: the UI only hides what it may not do.
Permission failures raise `frappe.PermissionError`, broken rules `frappe.ValidationError`.
Every status change is written inside `crm.privacy.system_write()`, because the request
refuses user writes to its status, approval and bookkeeping fields.
"""

import frappe
from frappe import _
from frappe.utils import add_months, cint, getdate, now_datetime, today

from crm.fcrm.doctype.crm_erasure_request.crm_erasure_request import FULL_ACCESS_ROLES
from crm.privacy import system_write
from crm.privacy.deadlines import day_number, days_left
from crm.privacy.erasure import placeholder_content
from crm.privacy.identifiers import normalize
from crm.privacy.matching import (
	SOURCES,
	_notify_deal_owners,
	active_identifiers,
	open_deals_with_person,
	refresh_identifiers,
	submit_request,
	suggest_matches,
)
from crm.privacy.preview import get_erasure_preview

REQUEST = "CRM Erasure Request"
AWAITING = "Awaiting Sign-off"
ON_HOLD = "On Hold"
ERASING = "Erasing"
LOGGED = "Logged"
DECLINABLE = (LOGGED, AWAITING, ON_HOLD)
CLOSABLE = ("Erased", "Declined")
RETENTION_MONTHS = 24
OUTCOMES = ("Completed", "Partly completed", "Denied")
KINDS = ("Email", "Phone")
START_DOCTYPES = ("CRM Lead", "Contact")

# What the logger sees of a request once it has left `Logged` (spec 5.1).
RESTRICTED_FIELDS = ("name", "status", "received_on", "acknowledge_by", "respond_by")
LIST_FIELDS = (
	"name",
	"request_type",
	"channel",
	"status",
	"received_on",
	"acknowledge_by",
	"respond_by",
	"logged_by",
	"requester_names",
	"acknowledgment_sent",
	"answered_on",
	"outcome",
)


# -- Who may do what ---------------------------------------------------------------------


def _roles() -> set[str]:
	return set(frappe.get_roles())


def _is_compliance() -> bool:
	return "Compliance" in _roles()


def _has_full_access() -> bool:
	return bool(_roles() & FULL_ACCESS_ROLES)


def _require_compliance() -> None:
	if not _is_compliance():
		frappe.throw(_("Only Compliance can do this."), frappe.PermissionError)


def _is_logger(request) -> bool:
	return request.logged_by == frappe.session.user


def _require_can_edit_matches(request) -> None:
	"""The logger while the request is `Logged`; Compliance until it is approved."""
	if _is_logger(request) and request.status == LOGGED:
		return
	if _is_compliance() and request.status in DECLINABLE:
		return
	frappe.throw(_("You cannot change this request."), frappe.PermissionError)


def _locked_request(name: str):
	"""The request, read under a row lock and so as it is now, not as an older snapshot of
	this transaction had it. Whoever changes the request next waits for this transaction, so
	two approvals (or an approval and a decline, or a match edit) cannot both go through.
	Every endpoint that changes a request starts here, before it looks at the status."""
	return frappe.get_doc(REQUEST, name, for_update=True)


def _save_as_system(request, **kwargs) -> None:
	with system_write():
		request.save(ignore_permissions=True, **kwargs)


def _numbers(request) -> dict:
	"""Days left and elapsed, counted from today."""
	received = getdate(request.get("received_on"))
	return {
		"days_left": days_left(received, getdate(today())),
		"day_number": day_number(received, getdate(today())),
	}


# -- Logging -----------------------------------------------------------------------------


def _clean_identifier(row: dict) -> dict | None:
	kind = (row.get("kind") or "").strip()
	value = (row.get("value") or "").strip()
	if not value:
		return None
	if kind not in KINDS:
		frappe.throw(_("Identifier kind must be Email or Phone, not {0}.").format(kind or _("empty")))
	return {"kind": kind, "value": value, "excluded": cint(row.get("excluded"))}


def _identifier_key(kind: str, value: str) -> tuple[str, str]:
	return kind, normalize(kind, value) or value.strip().lower()


def _identifiers_of_start_record(doctype: str, name: str) -> list[dict]:
	"""The emails and phones on a lead or contact, to start a request from."""
	record = frappe.get_doc(doctype, name)
	record.check_permission("read")

	found = []
	if doctype == "CRM Lead":
		found.append(("Email", record.email))
		found += [("Phone", record.mobile_no), ("Phone", record.phone)]
	else:
		found += [("Email", row.email_id) for row in record.get("email_ids") or []]
		found += [("Phone", row.phone) for row in record.get("phone_nos") or []]
		found.append(("Email", record.email_id))
		found += [("Phone", record.mobile_no), ("Phone", record.phone)]
	return [{"kind": kind, "value": value} for kind, value in found if value and value.strip()]


@frappe.whitelist()
def create_request(
	channel: str,
	received_on: str,
	requester_names: str = "",
	original_message: str = "",
	identifiers: list[dict] | None = None,
	start_doctype: str | None = None,
	start_name: str | None = None,
) -> str:
	"""Log a request. Started from a lead or contact, its emails and phones are prefilled and
	the record comes in as a confirmed match. Returns the request number."""
	if start_doctype or start_name:
		if start_doctype not in START_DOCTYPES or not start_name:
			frappe.throw(_("A request can only be started from a lead or a contact."))

	typed = [clean for row in identifiers or [] if (clean := _clean_identifier(row))]
	prefilled = _identifiers_of_start_record(start_doctype, start_name) if start_doctype else []

	request = frappe.get_doc(
		{
			"doctype": REQUEST,
			"channel": channel,
			"received_on": received_on,
			"requester_names": requester_names,
			"original_message": original_message,
		}
	)
	known = set()
	for row in typed + prefilled:
		key = _identifier_key(row["kind"], row["value"])
		if key not in known:
			known.add(key)
			request.append("identifiers", row)

	if start_doctype:
		request.append(
			"matches",
			{
				"reference_doctype": start_doctype,
				"reference_name": start_name,
				"confirmed": 1,
				"source": "Started from",
			},
		)

	refresh_identifiers(request)
	suggest_matches(request)
	request.insert()
	return request.name


# -- Reading -----------------------------------------------------------------------------


@frappe.whitelist()
def get_request(name: str) -> dict:
	"""The request in full, with `days_left` and `day_number`, for Compliance and Sales
	Managers and for the logger while it is `Logged`. After that the logger gets only
	status, dates and days left."""
	request = frappe.get_doc(REQUEST, name)

	if _has_full_access() or (_is_logger(request) and request.status == LOGGED):
		return {**request.as_dict(), **_numbers(request)}
	if _is_logger(request):
		return _restricted(request)
	frappe.throw(_("You do not have access to this request."), frappe.PermissionError)


def _restricted(row) -> dict:
	shape = {fieldname: row.get(fieldname) for fieldname in RESTRICTED_FIELDS}
	shape["days_left"] = _numbers(row)["days_left"]
	return shape


@frappe.whitelist()
def list_requests(include_closed: int = 0) -> list[dict]:
	"""Open requests, soonest deadline first. Full rows for Compliance and Sales Managers;
	everyone else sees only their own, in full while `Logged` and restricted after."""
	filters = {}
	if not cint(include_closed):
		filters["status"] = ["!=", "Closed"]
	full_access = _has_full_access()
	if not full_access:
		filters["logged_by"] = frappe.session.user

	rows = frappe.get_all(
		REQUEST, filters=filters, fields=list(LIST_FIELDS), order_by="respond_by asc, name asc"
	)
	result = []
	for row in rows:
		if full_access or row.status == LOGGED:
			result.append({**row, **_numbers(row)})
		else:
			result.append(_restricted(row))
	return result


# -- Before approval ---------------------------------------------------------------------


def _apply_matches(request, matches: list[dict]) -> None:
	"""Make the request's match rows the given list. Rows already there keep their source
	and `removed_from_open_deal`; only `confirmed` follows the list."""
	existing = {(row.reference_doctype, row.reference_name): row for row in request.matches}
	kept, added = [], []
	for item in matches or []:
		doctype, name = item.get("reference_doctype"), item.get("reference_name")
		key = (doctype, name)
		if key in existing:
			row = existing[key]
			row.confirmed = cint(item.get("confirmed"))
			kept.append(row)
			continue
		if doctype not in SOURCES:
			frappe.throw(_("A match must be a lead, a deal or a contact, not {0}.").format(doctype))
		if not name or not frappe.db.exists(doctype, name):
			frappe.throw(_("{0} {1} does not exist.").format(doctype, name))
		added.append(
			{
				"reference_doctype": doctype,
				"reference_name": name,
				"confirmed": cint(item.get("confirmed")),
				"source": "Identifier match",
			}
		)

	request.matches = kept
	for item in added:
		request.append("matches", item)
	for idx, row in enumerate(request.matches, 1):
		row.idx = idx


def _apply_identifiers(request, identifiers: list[dict]) -> None:
	"""Make the request's identifier rows the given list; `excluded` follows the list."""
	existing = {_identifier_key(row.kind, row.value): row for row in request.identifiers}
	kept, added = [], []
	for item in identifiers or []:
		clean = _clean_identifier(item)
		if not clean:
			continue
		key = _identifier_key(clean["kind"], clean["value"])
		if key in existing:
			row = existing.pop(key)
			row.excluded = clean["excluded"]
			kept.append(row)
		elif key not in {_identifier_key(a["kind"], a["value"]) for a in added}:
			added.append(clean)

	request.identifiers = kept
	for item in added:
		request.append("identifiers", item)
	for idx, row in enumerate(request.identifiers, 1):
		row.idx = idx


@frappe.whitelist()
def update_matches(name: str, matches: list[dict], identifiers: list[dict]) -> None:
	"""Replace the matched records and identifiers. The logger may while the request is
	`Logged`, Compliance until it is approved. Match counts are recounted."""
	request = _locked_request(name)
	_require_can_edit_matches(request)

	_apply_matches(request, matches)
	_apply_identifiers(request, identifiers)
	refresh_identifiers(request)
	request.save(ignore_permissions=True)


@frappe.whitelist()
def submit(name: str) -> str:
	"""Hand the request to Compliance. Returns the new status."""
	_require_can_edit_matches(_locked_request(name))
	return submit_request(name)


@frappe.whitelist()
def open_deals(name: str) -> list[str]:
	"""The open deals that hold the request On Hold, for the banner on the request page.
	Compliance and Sales Managers only."""
	if not _has_full_access():
		frappe.throw(_("You do not have access to this request."), frappe.PermissionError)
	return open_deals_with_person(frappe.get_doc(REQUEST, name))


@frappe.whitelist()
def preview(name: str) -> dict:
	"""What approving the request would remove and keep. Compliance only."""
	_require_compliance()
	return get_erasure_preview(name)


# -- Approval ----------------------------------------------------------------------------


def _hold(request, deals: list[str]) -> None:
	"""Put the request On Hold and ask the deals' owners to act, and make that stick even
	though the caller now raises."""
	request.status = ON_HOLD
	_save_as_system(request)
	_notify_deal_owners(request, deals)
	frappe.db.commit()


@frappe.whitelist()
def approve(name: str, typed_name: str) -> None:
	"""Approve the request and start the erasure job. The approver must be Compliance and
	not the logger, and type the request number. Only one approval can ever succeed."""
	user = frappe.session.user
	not_allowed = _("Only a Compliance user who did not log this request can approve it.")

	if not _is_compliance():
		frappe.throw(not_allowed, frappe.PermissionError)
	request = _locked_request(name)
	if not request.can_approve(user):
		frappe.throw(not_allowed, frappe.PermissionError)
	if (typed_name or "").strip() != name:
		frappe.throw(_("Type the request number exactly to confirm."))

	if request.status != AWAITING:
		if request.status in (ERASING, "Erased", "Closed"):
			frappe.throw(_("Request {0} is already approved.").format(name))
		frappe.throw(
			_("Only a request awaiting sign-off can be approved. This one is {0}.").format(request.status)
		)

	# A person may have been put on an open deal since the request was submitted.
	deals = open_deals_with_person(request)
	if deals:
		_hold(request, deals)
		frappe.throw(_("The person is on an open deal. The request is On Hold until that is resolved."))

	table = frappe.qb.DocType(REQUEST)
	(
		frappe.qb.update(table)
		.set(table.status, ERASING)
		.set(table.approved_by, user)
		.set(table.approved_on, now_datetime())
		# A save of an older copy of the request must fail the timestamp check, not undo this.
		.set(table.modified, now_datetime())
		.set(table.modified_by, user)
		.where(table.name == name)
		.where(table.status == AWAITING)
	).run()
	# The row lock above means the guard in the UPDATE always matches; this confirms it did.
	if frappe.db.get_value(REQUEST, name, ["status", "approved_by"]) != (ERASING, user):
		frappe.throw(_("Request {0} is already approved.").format(name))

	frappe.enqueue(
		"crm.privacy.erasure.run_erasure",
		request_name=name,
		queue="long",
		enqueue_after_commit=True,
	)


@frappe.whitelist()
def decline(name: str, reason: str) -> None:
	"""Decline the request, with a written reason. Compliance only, and not the logger."""
	_require_compliance()
	request = _locked_request(name)
	if _is_logger(request):
		frappe.throw(_("You cannot decline a request you logged."), frappe.PermissionError)
	if not (reason or "").strip():
		frappe.throw(_("A reason is required to decline a request."))

	if request.status not in DECLINABLE:
		frappe.throw(_("A request that is {0} cannot be declined.").format(request.status))

	request.status = "Declined"
	request.denial_reason = reason.strip()
	_save_as_system(request)


# -- Close -------------------------------------------------------------------------------


def _requester_values(request) -> set[str]:
	"""The values that identify the requester, read before the request is wiped: the
	identifiers (without the excluded, shared ones) and the lines of the requester names."""
	values = set(active_identifiers(request, "Email")) | set(active_identifiers(request, "Phone"))
	values.update(line.strip() for line in (request.requester_names or "").splitlines() if line.strip())
	return values


def _linked_communications(name: str) -> list[str]:
	"""Emails attached to the request: inbound mail from the requester while it was open."""
	linked = set(
		frappe.get_all(
			"Communication", filters={"reference_doctype": REQUEST, "reference_name": name}, pluck="name"
		)
	)
	linked.update(
		frappe.get_all(
			"Communication Link",
			filters={"link_doctype": REQUEST, "link_name": name, "parenttype": "Communication"},
			pluck="parent",
		)
	)
	return sorted(linked)


def _wipe_details(request) -> None:
	"""Drop everything that identifies the requester; the log entry stays."""
	placeholder = placeholder_content(request.name)
	request.requester_names = ""
	request.original_message = ""
	request.contract_references = ""
	request.identifiers = []
	request.matches = []
	for row in request.checklist:
		row.description = placeholder  # the description is mandatory: it keeps its row


def _wipe_comments(name: str) -> None:
	"""Comments on the request (Compliance's notes) may name the person."""
	frappe.db.set_value(
		"Comment",
		{"reference_doctype": REQUEST, "reference_name": name},
		"content",
		placeholder_content(name),
		update_modified=False,
	)


@frappe.whitelist()
def close(name: str, answered_on: str, outcome: str, denial_reason: str = "") -> None:
	"""Close an erased or declined request once the answer is sent. Wipes its identifying
	details and its history, and keeps the log entry for 24 months. Compliance only."""
	from crm.privacy.erasure import erase_communications

	_require_compliance()
	request = _locked_request(name)
	if request.status not in CLOSABLE:
		frappe.throw(_("Only an erased or declined request can be closed."))

	if not answered_on:
		frappe.throw(_("Date answered is required to close a request."))
	if outcome not in OUTCOMES:
		frappe.throw(_("An outcome is required to close a request."))
	if request.status == "Declined" and outcome != "Denied":
		frappe.throw(_("A declined request was not carried out: its outcome can only be Denied."))

	request.answered_on = getdate(answered_on)
	request.outcome = outcome
	request.denial_reason = (denial_reason or "").strip() or request.denial_reason
	request.status = "Closed"
	request.delete_after = add_months(request.answered_on, RETENTION_MONTHS)
	# The rules fail here, before anything is erased.
	request.validate_status_rules()

	person_values = _requester_values(request)
	emails = _linked_communications(name)
	if emails:
		erase_communications(emails, name, person_values)

	_wipe_details(request)
	_wipe_comments(name)
	_save_as_system(request, ignore_version=True)
	frappe.db.delete("Version", {"ref_doctype": REQUEST, "docname": name})


# -- Privacy settings --------------------------------------------------------------------


def _settings_doc(permission: str):
	doc = frappe.get_doc("CRM Privacy Settings")
	doc.check_permission(permission)
	return doc


@frappe.whitelist()
def get_privacy_settings() -> dict:
	"""The settings the Privacy page edits. The hash secret is never part of it."""
	doc = _settings_doc("read")
	return {
		"head_of_compliance": doc.head_of_compliance,
		"contract_retention_months": cint(doc.contract_retention_months),
		"personal_fields": [
			{"document_type": row.document_type, "fieldname": row.fieldname} for row in doc.personal_fields
		],
	}


@frappe.whitelist()
def save_privacy_settings(
	head_of_compliance: str | None = None,
	contract_retention_months: int = 0,
	personal_fields: list[dict] | None = None,
) -> dict:
	"""Save the Head of Compliance, the contract retention period and the personal fields.
	Each field must exist on its document type. Only people who may write the settings can
	do this; the stored hash secret is left as it is."""
	doc = _settings_doc("write")
	months = cint(contract_retention_months)
	if months < 0:
		frappe.throw(_("The retention period cannot be negative."))

	doc.head_of_compliance = head_of_compliance or None
	doc.contract_retention_months = months
	doc.set("personal_fields", [])
	for row in personal_fields or []:
		doc.append(
			"personal_fields",
			{"document_type": row.get("document_type"), "fieldname": (row.get("fieldname") or "").strip()},
		)
	doc.save()
	return get_privacy_settings()
