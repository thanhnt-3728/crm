# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""File bytes that a purge cannot wait on for ever (phase 06 fix round 1, M3).

A closed request lists the bytes its close could not delete. The purge tries to finish them first. If that keeps
failing (a permission, a path that cannot be removed), the request would live on past its 24 months with file names
that may carry her name. So the purge waits at most `MAX_BYTE_DELETE_FAILURES` daily attempts, counted by a
`["failures", n]` marker kept in the same list (it holds no personal data, and `file_bytes` ignores it). On the last
attempt it goes ahead: the request is deleted, the paths are written to the site log `erasure_cleanup` for a person to
remove, and Compliance is notified once.
"""

import json

import frappe
from frappe import _

from crm.privacy.erasure import file_bytes
from crm.privacy.error_log import log_privacy_error
from crm.privacy.request_visibility import DOCTYPE
from crm.privacy.roles import get_compliance_users

MAX_BYTE_DELETE_FAILURES = 5
FAILURES = "failures"
SAVEPOINT = "crm_purge_bytes"


def is_marker(entry) -> bool:
	return bool(entry) and entry[0] == FAILURES


def failures_of(pending: list) -> int:
	return next((int(entry[1]) for entry in pending if is_marker(entry)), 0)


def settle_bytes(request: str) -> tuple[bool, list]:
	"""Try to finish the bytes listed on `request`. Returns (go ahead with the purge, entries given up on)."""
	pending = file_bytes.pending_of(request)
	if not pending:
		return True, []
	frappe.db.savepoint(SAVEPOINT)
	failed = None
	try:
		file_bytes.finish_pending(request)
		return True, []
	except Exception as error:  # the class name is all that is logged
		failed = type(error).__name__
	frappe.db.rollback(save_point=SAVEPOINT)
	failures = failures_of(pending) + 1
	kept = [entry for entry in pending if not is_marker(entry)]
	frappe.db.set_value(
		DOCTYPE,
		request,
		"pending_file_deletions",
		json.dumps([*kept, [FAILURES, failures]]),
		update_modified=False,
	)
	log_privacy_error(
		request,
		f"{failed}; byte deletion attempt {failures} of {MAX_BYTE_DELETE_FAILURES}",
		reference_doctype=DOCTYPE,
		reference_name=request,
	)
	if failures >= MAX_BYTE_DELETE_FAILURES:
		return True, kept
	return False, []


def report_abandoned(request: str, entries: list) -> None:
	"""After the request is gone: write the paths where an administrator will look, and tell Compliance once. The
	Error Log and the notice carry the request number only; the file names stay in the site log file."""
	log = frappe.logger("erasure_cleanup", allow_site=True)
	for entry in entries:
		if len(entry) == 2:
			log.info(f"{request}: file bytes left behind, delete by hand: {entry[0]} (private={entry[1]})")
	text = _(
		"{0}: the request was purged but some of its file bytes could not be deleted. See the server's erasure_cleanup log."
	).format(request)
	for user in get_compliance_users():
		frappe.get_doc(
			{
				"doctype": "CRM Notification",
				"type": "Compliance",
				"to_user": user,
				"message": text,
				"notification_text": text,
			}
		).insert(ignore_permissions=True)
