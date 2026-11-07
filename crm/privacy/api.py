"""Whitelisted API behind the erasure request screens.

Every endpoint checks the caller server-side. Writes made here go through `doc.save()`
so the controller's write guard applies; this module adds the per-field role checks
and returns what the caller is allowed to see.
"""

import frappe
from frappe import _
from frappe.utils import getdate

from crm.privacy.deadlines import days_left
from crm.privacy.hold import apply_hold
from crm.privacy.identifiers import normalize_identifier
from crm.privacy.matching import (
	MANUAL_REASON,
	contact_identifiers,
	identifier_usage,
	lead_identifiers,
	record_title,
	refresh_matches,
)
from crm.privacy.permissions import FULL_ACCESS_ROLES, access_level, is_compliance

DOCTYPE = "CRM Erasure Request"
SOURCE_DOCTYPES = ("CRM Lead", "Contact", "CRM Deal")

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
	edit = (logger and status == "Logged") or (compliance and status not in ("Erased", "Closed"))
	return {
		"edit": edit,
		"submit": edit and status == "Logged",
		"approve": compliance and not logger and status == "Awaiting Sign-off",
		"decline": compliance and status in ("Logged", "Awaiting Sign-off", "On Hold"),
		"close": compliance and status in ("Erased", "Declined"),
		"manage_checklist": compliance and status != "Closed",
	}


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
	_require(_can(doc)["edit"])
	refresh_matches(doc)
	doc.save()
	return get_request(name)


@frappe.whitelist()
def submit_request(name: str) -> dict:
	"""Send a Logged request for sign-off; it waits On Hold while the person is on an open deal."""
	doc = frappe.get_doc(DOCTYPE, name)
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
