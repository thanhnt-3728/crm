# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The checklist of outside copies and the acknowledgment (design 5.7, 5.2; phase 06).

Compliance only, checked here on the server by an explicit role row. They match the `manage_checklist` and
`mark_acknowledged` flags of `get_request`: any request that is not Closed and not frozen by a running erasure,
before the erasure too (to plan) and after a decline. Writes run inside `server_write()`, so an Erased request
(a record that nothing else may change) still takes a tick.
"""

import frappe
from frappe import _
from frappe.utils import cint, getdate, now_datetime, today

from crm.privacy.erasure.approval import load, require_compliance
from crm.privacy.request_status import CLOSED, assert_not_frozen, server_write

DESCRIPTION_LENGTH = 500


def open_request(name: str, user: str, action: str):
	"""The request locked for a change by Compliance; refused when closed or while the erasure runs."""
	require_compliance(user, action)
	doc = load(name)
	if doc.status == CLOSED:
		frappe.throw(_("A closed request can no longer be changed"))
	assert_not_frozen(doc.erasure_job_status)
	return doc


def _save(doc) -> None:
	with server_write():
		doc.save(ignore_permissions=True)


def add_item(name: str, description: str | None, user: str):
	doc = open_request(name, user, _("manage the checklist of"))
	text = (description or "").strip()
	if not text:
		frappe.throw(_("Describe the checklist item"))
	if len(text) > DESCRIPTION_LENGTH:
		frappe.throw(_("A checklist item can have at most {0} characters").format(DESCRIPTION_LENGTH))
	doc.append("checklist", {"description": text, "auto_added": 0, "done": 0})
	_save(doc)
	return doc


def set_done(name: str, row: str, done, user: str):
	"""Tick (who and when are recorded) or untick one item of this request."""
	doc = open_request(name, user, _("manage the checklist of"))
	item = next((r for r in doc.checklist if r.name == row), None)
	if not item:
		frappe.throw(_("Checklist item not found on this request"))
	ticked = bool(cint(done))
	item.update(
		{
			"done": int(ticked),
			"done_by": user if ticked else None,
			"done_on": now_datetime() if ticked else None,
		}
	)
	_save(doc)
	return doc


def acknowledge(name: str, acknowledged_on, user: str, day=None):
	"""Record that the requester was acknowledged, on a day between the date received and today."""
	doc = open_request(name, user, _("acknowledge"))
	if doc.acknowledgment_sent:
		frappe.throw(_("The acknowledgment is already recorded"))
	today_ = getdate(day or today())
	given = getdate(acknowledged_on or today_)
	if given < getdate(doc.date_received) or given > today_:
		frappe.throw(_("The acknowledgment date must be between the date received and today"))
	doc.update({"acknowledgment_sent": 1, "acknowledged_on": given})
	_save(doc)
	return doc
