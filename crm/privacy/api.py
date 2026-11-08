"""Whitelisted API behind the erasure request screens.

Every endpoint checks the caller server-side. Writes made here go through `doc.save()`
so the controller's write guard applies; this module adds the per-field role checks
and returns what the caller is allowed to see.
"""

import frappe
from frappe import _
from frappe.utils import cint, getdate

from crm.privacy import lifecycle
from crm.privacy.deadlines import days_left
from crm.privacy.hold import apply_hold
from crm.privacy.identifiers import normalize_identifier
from crm.privacy.inbound import blocked_email, request_blocking
from crm.privacy.matching import (
	MANUAL_REASON,
	contact_identifiers,
	identifier_usage,
	lead_identifiers,
	record_title,
	refresh_matches,
)
from crm.privacy.permissions import FULL_ACCESS_ROLES, access_level, is_compliance
from crm.privacy.plan import plan_erasure, preview

DOCTYPE = "CRM Erasure Request"
SOURCE_DOCTYPES = ("CRM Lead", "Contact", "CRM Deal")
OUTCOMES = ("Completed", "Partly completed", "Denied")

SIMPLE_KEYS = (
	"arrived_via",
	"date_received",
	"requester_name",
	"other_names",
	"original_message",
	"contract_references",
	"acknowledgment_sent",
	"acknowledged_on",
)
TABLE_KEYS = ("identifiers", "matches", "checklist")
ALLOWED_KEYS = SIMPLE_KEYS + TABLE_KEYS
CHECKLIST_KEYS = ("acknowledgment_sent", "acknowledged_on")
# These need manage_checklist instead of edit, so Compliance can tick items after Erased.
CHECKLIST_ONLY_KEYS = ("checklist", *CHECKLIST_KEYS)


def _days_left(status: str, received) -> int | None:
	if status == "Closed":
		return None
	return days_left(getdate(received), getdate())


def _can(doc, user: str | None = None) -> dict:
	user = user or frappe.session.user
	compliance = is_compliance(user)
	logger = doc.logged_by == user
	status = doc.status
	# Once approved the job re-reads the request, so nothing may change until it has run.
	queued = doc.erasure_status == "Queued"
	edit = not queued and ((logger and status == "Logged") or (compliance and status not in ("Erased", "Closed")))
	return {
		"edit": edit,
		"submit": edit and status == "Logged",
		"approve": compliance and not logger and not queued and status == "Awaiting Sign-off",
		"decline": compliance and not queued and status in ("Logged", "Awaiting Sign-off", "On Hold"),
		"close": compliance and status in ("Erased", "Declined"),
		"manage_checklist": compliance and not queued and status != "Closed",
	}


def _refuse_while_queued(doc) -> None:
	"""The erasure job plans from the request when it runs: edits, a decline or a second
	approval made while it waits would change or race what it erases."""
	if doc.erasure_status == "Queued":
		frappe.throw(_("This request is being erased and cannot be changed"), frappe.ValidationError)


def _typed_identifiers(pairs: list[tuple[str, str | None]]) -> list[dict]:
	rows, seen = [], set()
	for kind, raw in pairs:
		value = normalize_identifier(kind, raw)
		if not value or (kind, value) in seen:
			continue
		seen.add((kind, value))
		rows.append({"kind": kind, "value": value, "source": "Typed", "excluded": 0})
	return rows


def _source_details(doctype: str, name: str) -> tuple[str | None, list[tuple[str, str | None]]]:
	"""The requester's name and the identifiers typed on a lead, contact or deal."""
	if doctype == "CRM Lead":
		return frappe.db.get_value("CRM Lead", name, "lead_name"), lead_identifiers(name)
	if doctype == "Contact":
		return frappe.db.get_value("Contact", name, "full_name"), contact_identifiers(name)

	email, mobile_no, phone = frappe.db.get_value("CRM Deal", name, ["email", "mobile_no", "phone"])
	contacts = frappe.get_all(
		"CRM Contacts",
		filters={"parent": name, "parenttype": "CRM Deal"},
		fields=["contact", "full_name", "is_primary"],
		order_by="idx asc",
		parent_doctype="CRM Deal",
	)
	primary = next((c for c in contacts if c.is_primary), contacts[0] if contacts else None)
	requester = None
	if primary:
		requester = primary.full_name or frappe.db.get_value("Contact", primary.contact, "full_name")
	return requester, [("Email", email), ("Phone", mobile_no), ("Phone", phone)]


@frappe.whitelist()
def log_request(source_doctype: str | None = None, source_name: str | None = None) -> str:
	"""Create an erasure request, optionally from a lead, contact or deal. Returns its name."""
	doc = frappe.new_doc(DOCTYPE)
	if source_doctype or source_name:
		if source_doctype not in SOURCE_DOCTYPES or not source_name:
			frappe.throw(_("Choose a lead, contact or deal to log the request from"), frappe.ValidationError)
		if not frappe.has_permission(source_doctype, "read", source_name):
			frappe.throw(_("You do not have access to that record"), frappe.PermissionError)

		requester, pairs = _source_details(source_doctype, source_name)
		doc.requester_name = requester
		for row in _typed_identifiers(pairs):
			doc.append("identifiers", row)
		doc.append(
			"matches",
			{
				"reference_doctype": source_doctype,
				"reference_name": source_name,
				"title": record_title(source_doctype, source_name),
				"reason": "Logged from this record",
				"confirmed": 1,
			},
		)
		refresh_matches(doc)
	doc.insert()
	return doc.name


@frappe.whitelist()
def get_erasure_preview(name: str) -> dict:
	"""What approving the request would remove and keep. Compliance only."""
	if not is_compliance():
		frappe.throw(_("Only Compliance can preview an erasure"), frappe.PermissionError)
	return preview(plan_erasure(frappe.get_doc(DOCTYPE, name)))


@frappe.whitelist()
def get_requests() -> list[dict]:
	"""The request list: everything for Compliance and Sales Manager, else the caller's own."""
	user = frappe.session.user
	filters = {}
	if not set(frappe.get_roles(user)) & set(FULL_ACCESS_ROLES):
		filters["logged_by"] = user
	rows = frappe.get_all(
		DOCTYPE,
		filters=filters,
		fields=[
			"name",
			"status",
			"date_received",
			"acknowledge_by",
			"respond_by",
			"logged_by",
			"requester_name",
		],
	)
	result = []
	for row in rows:
		full = access_level(row, user) == "full"
		result.append(
			{
				"name": row.name,
				"status": row.status,
				"date_received": row.date_received,
				"acknowledge_by": row.acknowledge_by,
				"respond_by": row.respond_by,
				"days_left": _days_left(row.status, row.date_received),
				"logged_by": row.logged_by,
				"requester_name": row.requester_name if full else None,
			}
		)
	open_rows = sorted((r for r in result if r["status"] != "Closed"), key=lambda r: r["days_left"])
	closed = sorted((r for r in result if r["status"] == "Closed"), key=lambda r: r["date_received"], reverse=True)
	return open_rows + closed


@frappe.whitelist()
def get_request(name: str) -> dict:
	"""One request, as much of it as the caller may see."""
	doc = frappe.get_doc(DOCTYPE, name)
	access = access_level(doc)
	if not access:
		frappe.throw(_("You do not have access to this request"), frappe.PermissionError)

	out = {
		"access": access,
		"name": doc.name,
		"status": doc.status,
		"acknowledge_by": doc.acknowledge_by,
		"respond_by": doc.respond_by,
		"days_left": _days_left(doc.status, doc.date_received),
	}
	if access != "full":
		return out

	out["doc"] = doc.as_dict()
	out["identifier_usage"] = identifier_usage(doc)
	out["emails"] = frappe.get_all(
		"Communication",
		filters={"reference_doctype": DOCTYPE, "reference_name": doc.name},
		fields=["name", "subject", "sender", "communication_date"],
		order_by="communication_date desc",
	)
	out["can"] = _can(doc)
	return out


def _same(current, value) -> bool:
	return str(current or "") == str(value or "")


def _require(allowed: bool) -> None:
	if not allowed:
		frappe.throw(_("You are not allowed to change this request"), frappe.PermissionError)


def _merge_identifiers(doc, rows: list[dict]) -> None:
	existing = {row.name: row for row in doc.identifiers}
	for item in rows:
		if item.get("name"):
			row = existing.get(item["name"])
			if not row:
				frappe.throw(_("Unknown identifier row"), frappe.ValidationError)
			if "excluded" in item:
				row.excluded = 1 if item["excluded"] else 0
			continue
		kind = item.get("kind")
		if kind not in ("Email", "Phone"):
			frappe.throw(_("Identifier kind must be Email or Phone"), frappe.ValidationError)
		doc.append("identifiers", {"kind": kind, "value": item.get("value"), "source": "Typed", "excluded": 0})


def _merge_matches(doc, rows: list[dict]) -> None:
	existing = {row.name: row for row in doc.matches}
	for item in rows:
		if item.get("name"):
			row = existing.get(item["name"])
			if not row:
				frappe.throw(_("Unknown match row"), frappe.ValidationError)
			if "confirmed" in item:
				row.confirmed = 1 if item["confirmed"] else 0
			continue
		doctype, name = item.get("reference_doctype"), item.get("reference_name")
		if doctype not in SOURCE_DOCTYPES or not name:
			frappe.throw(_("Choose a lead, contact or deal"), frappe.ValidationError)
		if not frappe.has_permission(doctype, "read", name):
			frappe.throw(_("You do not have access to that record"), frappe.PermissionError)
		confirmed = 1 if item.get("confirmed") else 0
		same = next((r for r in doc.matches if (r.reference_doctype, r.reference_name) == (doctype, name)), None)
		if same:
			same.confirmed = confirmed or same.confirmed
			continue
		doc.append(
			"matches",
			{
				"reference_doctype": doctype,
				"reference_name": name,
				"title": record_title(doctype, name),
				"reason": MANUAL_REASON,
				"confirmed": confirmed,
			},
		)


def _merge_checklist(doc, rows: list[dict]) -> None:
	existing = {row.name: row for row in doc.checklist}
	for item in rows:
		if item.get("name"):
			row = existing.get(item["name"])
			if not row:
				frappe.throw(_("Unknown checklist row"), frappe.ValidationError)
			if "done" in item:
				row.done = 1 if item["done"] else 0
			continue
		description = (item.get("description") or "").strip()
		if not description:
			frappe.throw(_("A checklist item needs a description"), frappe.ValidationError)
		doc.append("checklist", {"description": description})


@frappe.whitelist()
def save_request(name: str, values: dict) -> dict:
	"""Apply the allowed edits to a request and return the refreshed view."""
	values = frappe.parse_json(values) or {}
	if not isinstance(values, dict):
		frappe.throw(_("Invalid values"), frappe.ValidationError)
	unknown = [key for key in values if key not in ALLOWED_KEYS]
	if unknown:
		frappe.throw(_("These fields cannot be changed here: {0}").format(", ".join(unknown)), frappe.ValidationError)
	for key in TABLE_KEYS:
		if key in values:
			rows = values[key] or []
			if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
				frappe.throw(_("Invalid rows for {0}").format(key), frappe.ValidationError)
			values[key] = rows

	doc = frappe.get_doc(DOCTYPE, name)
	_refuse_while_queued(doc)
	can = _can(doc)
	if any(key not in CHECKLIST_ONLY_KEYS for key in values):
		_require(can["edit"])
	for key, value in values.items():
		if key == "checklist":
			_require(can["manage_checklist"] or not value)
		elif key in CHECKLIST_KEYS:
			_require(can["manage_checklist"] or _same(doc.get(key), value))
		elif key == "contract_references":
			_require(is_compliance() or _same(doc.get(key), value))

	for key in SIMPLE_KEYS:
		if key in values:
			doc.set(key, values[key])
	if "identifiers" in values:
		_merge_identifiers(doc, values["identifiers"] or [])
	if "matches" in values:
		_merge_matches(doc, values["matches"] or [])
	if "checklist" in values:
		_merge_checklist(doc, values["checklist"] or [])

	if any(key not in CHECKLIST_ONLY_KEYS for key in values):
		refresh_matches(doc)
	doc.save()
	return get_request(name)


@frappe.whitelist()
def refresh_request_matches(name: str) -> dict:
	"""Recompute suggested matches (e.g. after the identifiers changed elsewhere)."""
	doc = frappe.get_doc(DOCTYPE, name)
	_refuse_while_queued(doc)
	_require(_can(doc)["edit"])
	refresh_matches(doc)
	doc.save()
	return get_request(name)


@frappe.whitelist()
def submit_request(name: str) -> dict:
	"""Send a Logged request for sign-off; it waits On Hold while the person is on an open deal."""
	doc = frappe.get_doc(DOCTYPE, name)
	_refuse_while_queued(doc)
	_require(_can(doc)["submit"])
	has_match = any(row.confirmed for row in doc.matches)
	has_identifier = any(not row.excluded for row in doc.identifiers)
	if not (has_match or has_identifier):
		frappe.throw(_("Confirm a match or add an identifier before submitting"), frappe.ValidationError)

	# The caller passed the submit check above; a logger without Compliance may not change status.
	doc.flags.privacy_system_write = True
	doc.flags.ignore_permissions = True
	doc.status = "Awaiting Sign-off"
	doc.save()
	apply_hold(doc)
	return get_request(name)


@frappe.whitelist()
def approve_request(name: str, confirmation: str) -> dict:
	"""Approve an erasure: queue the job, or put the request On Hold if she is on an open deal.

	The approver types the request number to confirm. There is no undo.
	"""
	if not is_compliance():
		frappe.throw(_("Only Compliance can approve an erasure"), frappe.PermissionError)
	doc = frappe.get_doc(DOCTYPE, name)
	if doc.logged_by == frappe.session.user:
		frappe.throw(_("The person who logged a request cannot approve it"), frappe.PermissionError)
	if doc.status != "Awaiting Sign-off":
		frappe.throw(_("Only a request awaiting sign-off can be approved"), frappe.ValidationError)
	_refuse_while_queued(doc)
	if (confirmation or "").strip() != doc.name:
		frappe.throw(_("Type the request number {0} to confirm").format(doc.name), frappe.ValidationError)
	if (doc.contract_references or "").strip() and not (
		cint(frappe.db.get_single_value("CRM Privacy Settings", "contract_retention_months")) > 0
	):
		frappe.throw(
			_("Set a contract retention period in Privacy Settings before erasing a request with contracts"),
			frappe.ValidationError,
		)
	if apply_hold(doc):
		return get_request(name)

	frappe.db.set_value(DOCTYPE, name, {"erasure_status": "Queued", "erasure_error": ""})
	frappe.enqueue(
		"crm.privacy.erasure.run_erasure",
		queue="long",
		job_id=f"erasure-{name}",
		deduplicate=True,
		enqueue_after_commit=True,
		request=name,
		approver=frappe.session.user,
	)
	return get_request(name)


@frappe.whitelist()
def decline_request(name: str, reason: str) -> dict:
	"""Decline a request that has not been erased. The reason is required."""
	if not is_compliance():
		frappe.throw(_("Only Compliance can decline a request"), frappe.PermissionError)
	doc = frappe.get_doc(DOCTYPE, name)
	_refuse_while_queued(doc)
	if not _can(doc)["decline"]:
		frappe.throw(_("This request can no longer be declined"), frappe.ValidationError)
	reason = (reason or "").strip()
	if not reason:
		frappe.throw(_("Give a reason for declining"), frappe.ValidationError)

	doc.flags.privacy_system_write = True
	doc.flags.ignore_permissions = True
	doc.status = "Declined"
	doc.decline_reason = reason
	doc.save()
	return get_request(name)


def _blocked_email(name: str):
	"""The blocked mail `name`, for a Compliance user. Anything else gets the same refusal,
	which never names the sender."""
	doc = blocked_email(name) if is_compliance() else None
	if not doc:
		frappe.throw(_("This email is not available"), frappe.PermissionError)
	return doc


@frappe.whitelist()
def get_blocked_email(name: str) -> dict:
	"""Mail that arrived from an erased person after her request closed. Compliance only.

	This is the only way to read it: Compliance has no general read on Communication, and
	the mail is attached to no record.
	"""
	doc = _blocked_email(name)
	return {
		"name": doc.name,
		"sender": doc.sender,
		"sender_full_name": doc.sender_full_name,
		"communication_date": doc.communication_date,
		"subject": doc.subject,
		"content": doc.content,
		"request": request_blocking(doc.sender),
		"attachments": frappe.get_all(
			"File",
			filters={"attached_to_doctype": "Communication", "attached_to_name": doc.name, "is_folder": 0},
			fields=["name", "file_name", "file_size", "is_private"],
			order_by="creation asc",
		),
	}


@frappe.whitelist(methods=["GET"])
def download_blocked_email_attachment(email: str, file: str) -> None:
	"""Stream one attachment of a blocked mail. Compliance only.

	Needed because File permission defers a private file to the Communication it is
	attached to, which Compliance cannot read.
	"""
	doc = _blocked_email(email)
	row = frappe.db.get_value(
		"File", file, ["name", "attached_to_doctype", "attached_to_name", "is_folder"], as_dict=True
	)
	if not row or row.is_folder or (row.attached_to_doctype, row.attached_to_name) != ("Communication", doc.name):
		frappe.throw(_("This email is not available"), frappe.PermissionError)
	attachment = frappe.get_doc("File", row.name)
	frappe.local.response.filename = attachment.file_name
	frappe.local.response.filecontent = attachment.get_content()
	frappe.local.response.type = "download"


@frappe.whitelist()
def close_request(name: str, date_answered: str | None, outcome: str, denial_reason: str | None = None) -> dict:
	"""Close an erased or declined request and wipe what is left of the person on it.

	There is no undo: the identifiers, matches and free text are removed.
	"""
	if not is_compliance():
		frappe.throw(_("Only Compliance can close a request"), frappe.PermissionError)
	doc = frappe.get_doc(DOCTYPE, name)
	if not _can(doc)["close"]:
		frappe.throw(_("Only an erased or declined request can be closed"), frappe.ValidationError)

	if outcome not in OUTCOMES:
		frappe.throw(_("Choose an outcome: {0}").format(", ".join(OUTCOMES)), frappe.ValidationError)
	if doc.status == "Declined" and outcome != "Denied":
		frappe.throw(_("A declined request can only be closed as Denied"), frappe.ValidationError)
	reason = (denial_reason or "").strip() or (doc.decline_reason or "").strip()
	if outcome == "Denied" and not reason:
		frappe.throw(_("Give the reason the request was denied"), frappe.ValidationError)
	if any(not row.done for row in doc.checklist):
		frappe.throw(_("Finish every checklist item before closing"), frappe.ValidationError)

	# getdate() turns an empty value into today, so a blank date is refused first.
	if not str(date_answered or "").strip():
		frappe.throw(_("Enter the date the requester was answered"), frappe.ValidationError)
	try:
		answered = getdate(date_answered)
	except Exception:
		frappe.throw(_("Enter the date the requester was answered"), frappe.ValidationError)
	if answered < getdate(doc.date_received):
		frappe.throw(_("The answer date cannot be before the date received"), frappe.ValidationError)
	if answered > getdate():
		frappe.throw(_("The answer date cannot be in the future"), frappe.ValidationError)

	# Checks above passed for a Compliance user; the writes are the system's.
	frappe.db.set_value(
		DOCTYPE,
		name,
		{
			"date_answered": answered,
			"outcome": outcome,
			"denial_reason": reason if outcome == "Denied" else "",
		},
		update_modified=False,
	)
	lifecycle.close(doc)
	return get_request(name)
