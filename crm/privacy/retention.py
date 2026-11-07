# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The daily purge (design 5.8, 5.11; phase 06; RT-12, V1).

* Retained contracts whose `delete_after` has come are deleted first, in their own loop, so a closed request that
  cannot be deleted never starves them.
* Closed requests whose `purge_after` has come are deleted: whatever still points at the request is cleared or
  deleted first (emails are unlinked, comments, notices, queued mail and files are deleted), so the link check cannot
  fail on a leftover. The bytes and global search rows of what was deleted go after the commit.
* Last, closed requests that still list bytes are finished (the hourly sweeper does this too).

Deletes are permanent (no Deleted Document copy). Each row runs in its own savepoint: a failure is logged with the
request number and the exception class only, and the loop goes on. Do-not-contact entries are never touched. Safe to
run twice, and a missed day is made up the next day (`<=`).
"""

import frappe
from frappe.utils import getdate

from crm.privacy.erasure import file_bytes
from crm.privacy.error_log import log_privacy_error
from crm.privacy.on_hold import _isolated
from crm.privacy.request_scrub import (
	delete_comments_on_emails,
	detach_communications,
	request_communications,
)
from crm.privacy.request_scrub_rows import delete_files, delete_mail_traces
from crm.privacy.request_search import finish_entries
from crm.privacy.request_status import CLOSED
from crm.privacy.request_visibility import DOCTYPE
from crm.privacy.retention_bytes import MAX_BYTE_DELETE_FAILURES, report_abandoned, settle_bytes

CONTRACT = "CRM Retained Contract"
CONTRACT_TITLE = "Retained contract purge"
__all__ = ["MAX_BYTE_DELETE_FAILURES", "purge_expired"]


def delete_permanently(doctype: str, name: str) -> None:
	frappe.delete_doc(doctype, name, ignore_permissions=True, delete_permanently=True)


def purge_retained_contracts(day) -> None:
	for contract in frappe.get_all(
		CONTRACT,
		{"delete_after": ["<=", day]},
		["name", "request"],
		order_by="delete_after asc, creation asc",
	):
		request = (
			contract.request if contract.request and frappe.db.exists(DOCTYPE, contract.request) else None
		)
		with _isolated(request or CONTRACT_TITLE, request):
			delete_permanently(CONTRACT, contract.name)


def clear_links(request: str) -> list[list]:
	"""Detach or delete everything that still references the request. Returns what to do after the commit (file
	bytes to delete, search rows to purge)."""
	communications = request_communications(request)
	pending = delete_files(request, communications)
	delete_mail_traces(request, communications, finished_only=False)
	delete_comments_on_emails(communications)
	detach_communications(request, communications)
	frappe.db.delete("Comment", {"reference_doctype": DOCTYPE, "reference_name": request})
	frappe.db.delete(
		"CRM Notification", {"notification_type_doctype": DOCTYPE, "notification_type_doc": request}
	)
	frappe.db.delete("CRM Notification", {"reference_doctype": DOCTYPE, "reference_name": request})
	return pending


def purge_request(request: str):
	"""One request, inside the caller's savepoint. Returns None when it must wait for its bytes, else
	(what to do after the commit, entries whose bytes could not be deleted)."""
	proceed, abandoned = settle_bytes(request)
	if not proceed:
		return None
	pending = clear_links(request)
	delete_permanently(DOCTYPE, request)
	return pending, abandoned


def purge_requests(day) -> None:
	"""Closed requests due on or before `day`. Bytes and search rows of leftovers are dealt with after the commit,
	and only for a request whose purge succeeded: a rolled back purge keeps its rows, so it keeps its bytes."""
	for request in frappe.get_all(
		DOCTYPE,
		{"status": CLOSED, "purge_after": ["<=", day]},
		pluck="name",
		order_by="purge_after asc, creation asc",
	):
		done = None
		with _isolated(request, request):
			done = purge_request(request)
		if not done:
			continue
		pending, abandoned = done
		if pending:
			frappe.db.after_commit.add(lambda pending=pending: finish_entries(pending))
		if abandoned:
			report_abandoned_safely(request, abandoned)


def report_abandoned_safely(request: str, abandoned: list) -> None:
	"""The request is gone already: a failure here is logged by number and class and never stops the run."""
	failed = None
	try:
		report_abandoned(request, abandoned)
	except Exception as error:
		failed = type(error).__name__
	if failed:
		log_privacy_error(request, failed)


def finish_closed_file_deletions(day) -> None:
	"""Closed requests that still list bytes (a close whose after-commit step failed) and are not due yet: finish
	them. The due ones were handled, with the failure cap, by `purge_requests`."""
	for request in frappe.get_all(
		DOCTYPE,
		{"status": CLOSED, "pending_file_deletions": ["is", "set"], "purge_after": [">", day]},
		pluck="name",
	):
		with _isolated(request, request):
			file_bytes.finish_pending(request)


def purge_expired(today=None) -> None:
	"""The daily job."""
	day = getdate(today)
	purge_retained_contracts(day)
	purge_requests(day)
	finish_closed_file_deletions(day)
