# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
"""What a plain save (form, REST, doc.save) may change on a CRM Erasure Request

Status and decision fields move only through the controller's transition methods, which set
`flags.erasure_transition`; these rules apply to every save without that flag.
"""

import json

import frappe
from frappe import _
from frappe.model import no_value_fields, table_fields
from frappe.utils import cint, flt, get_datetime, getdate, today

from crm.fcrm.doctype.crm_erasure_request.erasure_states import (
	DRAFT,
	PRIVACY_OFFICER_ROLE,
	TERMINAL_STATES,
	can_transition,
)

# Written only by server code (transitions, hold rule, execution job)
SYSTEM_FIELDS = (
	"hold_reason",
	"approver",
	"approved_on",
	"rejection_reason",
	"executed_on",
	"last_error",
	"outcome",
	"known_limitations",
)
# Recomputed by the controller on every save, so a sent value never sticks
COMPUTED_FIELDS = ("requested_by", "ack_due", "response_due")
EDITABLE_AFTER_DRAFT = ("acknowledged_on",)
# Who the request is about: set when it is logged, changed only through `set_identifiers`
FIXED_AFTER_INSERT = ("identifiers", "source_doctype", "source_docname")
# Child tables only the controller's seams write (replace_matches, set_match_exclusions)
SERVER_TABLES = ("matches",)
ACK_EDITOR_ROLES = (PRIVACY_OFFICER_ROLE, "System Manager")


def check_new_request(doc) -> None:
	"""A new request starts in Draft with no decision, outcome or matches recorded"""
	if (doc.status or DRAFT) != DRAFT:
		frappe.throw(_("A new erasure request must start as Draft"), frappe.ValidationError)
	forged = [f for f in (*SYSTEM_FIELDS, *SERVER_TABLES) if doc.get(f)]
	if forged:
		frappe.throw(_("Cannot set {0} on a new erasure request").format(", ".join(forged)))


def check_form_save(doc, before, user: str) -> None:
	"""Reject changes a plain save may not make, given the status stored before this save"""
	changed = changed_fields(doc, before) - set(COMPUTED_FIELDS)
	if not changed:
		return
	if "status" in changed:
		frappe.throw(_("Status of an erasure request changes only through its actions"))
	fixed = changed.intersection(FIXED_AFTER_INSERT)
	if fixed:  # a swapped identifier or source would point discovery at someone else
		frappe.throw(_("{0} cannot be changed once the request is logged").format(", ".join(sorted(fixed))))
	server_only = changed.intersection((*SYSTEM_FIELDS, *SERVER_TABLES))
	if server_only:
		frappe.throw(_("{0} cannot be edited").format(", ".join(sorted(server_only))))
	if before.status in TERMINAL_STATES:
		frappe.throw(_("A {0} erasure request cannot be edited").format(_(before.status)))
	if before.status == DRAFT and user == before.requested_by:
		return
	locked = changed - set(EDITABLE_AFTER_DRAFT)
	if locked:
		frappe.throw(
			_(
				"Only the requester can edit a Draft, and only Acknowledged On after it; cannot edit {0}"
			).format(", ".join(sorted(locked)))
		)
	if user != before.requested_by and not set(frappe.get_roles(user)).intersection(ACK_EDITOR_ROLES):
		frappe.throw(
			_("Only the requester or a Privacy Officer can set Acknowledged On"), frappe.PermissionError
		)


def check_internal_save(doc, before, allowed: set[str]) -> None:
	"""A transition or seam save may persist only the fields it declared, never stray edits"""
	stray = changed_fields(doc, before) - set(COMPUTED_FIELDS) - allowed
	if stray:
		frappe.throw(
			_("Unsaved changes to {0} cannot ride along with this action").format(", ".join(sorted(stray)))
		)
	if (doc.requested_by, doc.owner) != (before.requested_by, before.owner):
		frappe.throw(_("The requester and owner of an erasure request never change"))
	if doc.status != before.status and not can_transition(before.status, doc.status):
		frappe.throw(_("Erasure request cannot move from {0} to {1}").format(before.status, doc.status))


def assert_system_fields(fields: dict) -> None:
	unknown = set(fields) - set(SYSTEM_FIELDS)
	if unknown:
		raise ValueError(f"only system fields can be set here, not {sorted(unknown)}")


def check_dates(doc) -> None:
	received_on = getdate(doc.received_on)
	if received_on > getdate(today()):
		frappe.throw(_("Received On cannot be in the future"))
	if doc.acknowledged_on:
		acknowledged_on = getdate(doc.acknowledged_on)
		if acknowledged_on > getdate(today()):
			frappe.throw(_("Acknowledged On cannot be in the future"))
		if acknowledged_on < received_on:
			frappe.throw(_("Acknowledged On cannot be before Received On"))


def check_source(doc, user: str) -> None:
	"""The source record must exist and be readable by the user logging the request"""
	exists = doc.source_docname and frappe.db.exists(doc.source_doctype, doc.source_docname)
	if not exists or not frappe.has_permission(doc.source_doctype, "read", doc=doc.source_docname, user=user):
		frappe.throw(_("{0} {1} not found").format(_(doc.source_doctype), doc.source_docname))


def strip_client_normalized(doc, before) -> None:
	"""`identifiers.normalized` is server-computed: keep the stored value only for unchanged rows"""
	stored = {row.name: row for row in (before.get("identifiers") if before else None) or []}
	for row in doc.get("identifiers") or []:
		prev = stored.get(row.name)
		same = prev and (prev.kind, prev.value) == (row.kind, row.value)
		row.normalized = prev.normalized if same else None


def changed_fields(doc, before) -> set[str]:
	"""Fieldnames whose normalized value differs between `doc` and `before` (tables compared by rows)"""
	changed = set()
	for df in doc.meta.fields:
		if df.fieldtype in table_fields:
			if _rows(doc.get(df.fieldname)) != _rows(before.get(df.fieldname)):
				changed.add(df.fieldname)
		elif df.fieldtype not in no_value_fields:
			if _normalize(df.fieldtype, doc.get(df.fieldname)) != _normalize(
				df.fieldtype, before.get(df.fieldname)
			):
				changed.add(df.fieldname)
	return changed


def _rows(rows) -> list[dict]:
	result = []
	for row in rows or []:
		meta = frappe.get_meta(row.doctype)
		result.append(
			{
				df.fieldname: _normalize(df.fieldtype, row.get(df.fieldname))
				for df in meta.fields
				if df.fieldtype not in no_value_fields
			}
		)
	return result


def _normalize(fieldtype: str, value):
	"""Compare values the way the database stores them: '' == None, '1' == 1, str dates == dates"""
	if value in (None, ""):
		return None
	if fieldtype == "Date":
		return getdate(value)
	if fieldtype == "Datetime":
		return get_datetime(value).replace(microsecond=0)
	if fieldtype in ("Check", "Int"):
		return cint(value)
	if fieldtype in ("Float", "Currency", "Percent"):
		return flt(value)
	if fieldtype == "JSON":
		parsed = json.loads(value) if isinstance(value, str) else value
		return json.dumps(parsed, sort_keys=True, default=str)
	return str(value)
