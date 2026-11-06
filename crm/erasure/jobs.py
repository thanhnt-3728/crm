# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
"""The erasure job (F4): one transaction for the database work, then files, then the outcome

    lock request -> Approved, approver still a decider, no open deal? -> executor.run (File rows
    included) -> residual check -> Executed + outcome -> COMMIT -> disk files -> re-index -> notify

Any failure before the commit rolls the work back and records `last_error` (exception class and
registry doctype, or table names; never a value) in a fresh commit; the status stays Approved
and `retry_execution` enqueues the job again. The rollback goes to a savepoint taken right after
the lock, which in a worker is the start of the transaction (tests keep their fixture that way).
Exceptions never escape: RQ would log their traceback (it may quote her data) in Error Log.
"""

import json
from contextlib import contextmanager

import frappe
from frappe.utils import now_datetime

from crm.erasure import executor, post_commit, verify
from crm.erasure.execution_context import build_context
from crm.erasure.registry import KNOWN_LIMITATIONS
from crm.fcrm.doctype.crm_erasure_request.erasure_guards import ERASURE_EXECUTION_FLAG, stored_identity
from crm.fcrm.doctype.crm_erasure_request.erasure_hold import blocking_open_deals, format_hold_reason
from crm.fcrm.doctype.crm_erasure_request.erasure_states import APPROVED, EXECUTED, can_decide

REQUEST = "CRM Erasure Request"
JOB_METHOD = "crm.erasure.jobs.execute_request"
JOB_TIMEOUT = 1500
SAVEPOINT = "crm_erasure_execution"


class ResidualHits(Exception):
	def __init__(self, tables: list[str]):
		super().__init__("Her identifiers are still in: " + ", ".join(tables))


def enqueue_execution(name: str) -> None:
	"""Queue the job once per request; it starts only after the caller's transaction commits"""
	frappe.enqueue(
		JOB_METHOD,
		queue="long",
		timeout=JOB_TIMEOUT,
		job_id=f"crm-erasure::{name}",
		deduplicate=True,
		enqueue_after_commit=True,
		name=name,
	)


@contextmanager
def running_erasure(name: str):
	"""Mark `name`'s erasure as running: the rename guard lets it rename the records it references"""
	frappe.flags[ERASURE_EXECUTION_FLAG] = name
	try:
		yield
	finally:
		frappe.flags[ERASURE_EXECUTION_FLAG] = None


def execute_request(name: str) -> None:
	"""Job entry point (args: the request name only); safe to run again at any time"""
	request = frappe.get_doc(REQUEST, name, for_update=True)
	if request.status != APPROVED:
		return  # executed already, or never approved: nothing to do
	if not _approver_may_decide(request):
		_record_error(name, "The approver is no longer a Privacy Officer other than the requester")
		return
	deals = blocking_open_deals(request)  # a deal may have reopened since approval
	if deals:
		_record_error(name, f"On hold: deals {format_hold_reason(deals)} are open; retry once they are closed")
		return
	frappe.db.savepoint(SAVEPOINT)
	try:
		with running_erasure(name):
			changes = executor.run(request)
		request = frappe.get_doc(REQUEST, name)  # match rows now carry the new names of renamed records
		excluded = {(row.ref_doctype, row.ref_name) for row in request.matches if row.excluded}
		ids = build_context(request).ids
		hits = verify.residual_hits(ids, excluded=excluded)
		if hits:
			raise ResidualHits(hits)
		outcome = _outcome(changes, len(excluded), name)
		pending = outcome["pending_files"]
		request.transition_to(
			EXECUTED,
			executed_on=now_datetime(),
			outcome=json.dumps(outcome),
			known_limitations="\n".join(KNOWN_LIMITATIONS),
			# set until the disk files are gone: if the worker dies after the commit, this is the prompt
			last_error=post_commit.pending_hint(len(pending), name) if pending else None,
		)
	except Exception as e:
		_rollback()
		_restore_search(name)
		_record_error(name, _error_text(e))
		return
	frappe.db.commit()
	_after_commit(request, changes, ids, outcome)


def _after_commit(request, changes, ids, outcome: dict) -> None:
	failed = post_commit.delete_disk_files(changes.files, request.name)
	post_commit.reindex_search(changes, ids)
	post_commit.notify_and_clear_caches(_matched_keys(request))
	if failed or outcome["pending_files"]:
		outcome["pending_files"] = failed
		fields = {"outcome": json.dumps(outcome)}
		fields["last_error"] = post_commit.pending_hint(len(failed), request.name) if failed else None
		frappe.get_doc(REQUEST, request.name).save_system_fields(**fields)
		frappe.db.commit()


def _rollback() -> None:
	"""Back to the savepoint, and drop what the failed run queued for after the commit (realtime
	events such as doc_rename carry her old name; the error commit below would flush them)"""
	try:
		frappe.db.rollback(save_point=SAVEPOINT)
	except Exception:  # a deadlock already ended the transaction, and the savepoint with it
		frappe.db.rollback()
	frappe.db.after_commit.reset()
	if hasattr(frappe.local, "_realtime_log"):
		del frappe.local._realtime_log  # publish_realtime re-creates it and re-registers its flush


def _restore_search(name: str) -> None:
	"""`__global_search` is MyISAM: rows the failed run deleted are not rolled back, so re-index"""
	try:
		post_commit.reindex_records(_matched_keys(frappe.get_doc(REQUEST, name)))
	except Exception:
		pass  # search rows come back with the next save of each record


def _matched_keys(request) -> list[tuple[str, str]]:
	return [(row.ref_doctype, row.ref_name) for row in request.matches if not row.excluded]


def _approver_may_decide(request) -> bool:
	identity = stored_identity(request)
	approver = request.approver
	return bool(
		identity
		and approver
		and request.approved_on
		and can_decide(approver, frappe.get_roles(approver), identity.requested_by, identity.owner)
	)


def _outcome(changes, excluded_count: int, request_name: str) -> dict:
	"""Counts and record names only (names of doctypes named after a person are left out)"""
	return {
		"changed": dict(sorted(changes.counts.items())),
		"docs": changes.docs,
		"files_deleted": changes.counts.get("File", 0),
		"excluded_count": excluded_count,
		"skipped": dict(sorted(changes.skipped.items())),
		# sha256 of the site paths of disk files not deleted yet (a file name may spell her email)
		"pending_files": sorted({h for url in changes.files if (h := post_commit.pending_hash(url, request_name))}),
	}


def _error_text(e: Exception) -> str:
	if isinstance(e, ResidualHits | executor.ErasureStepFailed):
		return str(e)
	return f"{type(e).__name__} during the erasure"  # never str(e): it may quote her data


def _record_error(name: str, text: str) -> None:
	request = frappe.get_doc(REQUEST, name)
	request.save_system_fields(last_error=text)
	frappe.db.commit()
