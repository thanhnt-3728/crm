# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Closing a request (design 5.2, 5.8; phase 06; RT-8, RT-12).

Closing records the answer and wipes everything that identifies the requester: names, message, identifiers,
matches, checklist and contract references, the emails and files attached to the request. What stays is the log
entry (dates, type, channel, outcome, denial reason) until `purge_after`, 24 months on.

The whole close is one transaction. The File rows go inside it; the bytes are listed on the request
(`pending_file_deletions`) and deleted after the commit, so a rollback keeps rows and bytes together.
"""

import json
from functools import partial

import frappe
from frappe import _
from frappe.utils import add_months, getdate, global_search, today

from crm.privacy.erasure import file_bytes
from crm.privacy.erasure.approval import load, require_compliance
from crm.privacy.error_log import log_privacy_error
from crm.privacy.request_scrub import request_communications, scrub_request
from crm.privacy.request_scrub_rows import unsent_mail
from crm.privacy.request_search import resync_emails
from crm.privacy.request_status import (
	CLOSED,
	DECLINED,
	ERASED,
	assert_not_frozen,
	server_write,
)
from crm.privacy.request_visibility import DOCTYPE

OUTCOMES = ("Completed", "Partly completed", "Denied")
REASON_OUTCOMES = ("Partly completed", "Denied")
RETENTION_MONTHS = 24
CHILD_TABLES = ("identifiers", "matches", "checklist", "contract_references")


def answered_date(value, received, day):
	"""`value` as a date, between the date received and `day`."""
	if not value:
		frappe.throw(_("Enter the date the requester was answered"))
	answered = getdate(value)
	if answered < getdate(received) or answered > day:
		frappe.throw(_("The date answered must be between the date received and today"))
	return answered


def validate_close(doc, date_answered, outcome, denial_reason, day) -> dict:
	"""Check every rule and return the values to store; raises before anything is written."""
	if doc.status not in (ERASED, DECLINED):
		frappe.throw(_("Only an Erased or Declined request can be closed"))
	assert_not_frozen(doc.erasure_job_status)
	if doc.pending_file_deletions:
		frappe.throw(_("Files of this request are still being deleted. Try again shortly"))
	if any(not row.done for row in doc.checklist):
		frappe.throw(_("Every checklist item must be done before the request is closed"))
	if unsent_mail(request_communications(doc.name)):
		frappe.throw(
			_("The outcome email is still being sent. Wait for it to go out, or cancel the send, then close")
		)
	if outcome not in OUTCOMES:
		frappe.throw(_("Choose an outcome: {0}").format(", ".join(_(o) for o in OUTCOMES)))
	if (doc.status == DECLINED) != (outcome == "Denied"):
		frappe.throw(_("A declined request closes as Denied, and an erased one cannot"))
	reason = (denial_reason or "").strip() or (doc.denial_reason or "").strip()
	if outcome in REASON_OUTCOMES and not reason:
		frappe.throw(_("A denial reason is required when the outcome is {0}").format(_(outcome)))
	return {
		"date_answered": answered_date(date_answered, doc.date_received, day),
		"outcome": outcome,
		"denial_reason": reason if outcome in REASON_OUTCOMES else None,
	}


def wipe_request(doc) -> None:
	"""Names, message, the approved plan's digest and every child row (identifiers, matches, checklist, contract
	references)."""
	doc.update({"requester_names": None, "original_message": None, "approved_plan_hash": None})
	for table in CHILD_TABLES:
		doc.set(table, [])


def finish_closed_files(request: str) -> None:
	"""After the commit: flush the search queue, delete the bytes and search rows listed on the request, clear the
	list, and index the scrubbed emails again. A failure leaves the list, and the hourly sweeper finishes it. Only the
	request number and the exception class are logged."""
	failed = None
	try:
		global_search.sync_global_search()  # a queued item may still hold the old text
		pending = file_bytes.pending_of(request)
		file_bytes.finish_pending(request)
		resync_emails(pending)
		frappe.db.commit()  # nosemgrep
	except Exception as error:
		failed = type(error).__name__
	if failed:
		frappe.db.rollback()
		log_privacy_error(request, failed, reference_doctype=DOCTYPE, reference_name=request)
		frappe.db.commit()  # nosemgrep


def close(name: str, date_answered, outcome: str, denial_reason: str | None, user: str, day=None):
	"""Close an Erased or Declined request (Compliance only). Returns the closed request."""
	require_compliance(user, _("close"))
	day = getdate(day or today())
	doc = load(name)
	values = validate_close(doc, date_answered, outcome, denial_reason, day)
	pending = scrub_request(doc)
	wipe_request(doc)
	doc.update(
		{
			**values,
			"status": CLOSED,
			"closed_on": day,
			"purge_after": add_months(day, RETENTION_MONTHS),
			"pending_file_deletions": json.dumps(pending) if pending else None,
		}
	)
	with server_write():
		doc.save(ignore_permissions=True)
	if pending:  # registered last: a failure above rolls back and never reaches the bytes
		frappe.db.after_commit.add(partial(finish_closed_files, name))
	return doc
