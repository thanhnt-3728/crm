# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""How the erasure job ends other than by erasing: refused, back On Hold, failed, or finished (phase 05; V1).

Nothing here holds personal data: the messages are fixed text and the log carries the request number and the
exception class only.
"""

import frappe
from frappe import _

from crm.fcrm.doctype.crm_privacy_settings.crm_privacy_settings import DncSecretUnavailableError
from crm.privacy.erasure import file_bytes, scrub_search
from crm.privacy.erasure.plan import ErasurePlan
from crm.privacy.request_status import server_write
from crm.privacy.request_visibility import DOCTYPE

PLAN_CHANGED = "Plan changed since approval; review and approve again"
NOT_FINISHED = (
	"The erasure could not be completed and nothing was erased. Approve the request again to retry."
)
APPROVER_LOST = "The approver can no longer approve this request. Approve it again."
SECRET_MISSING = "Privacy settings are incomplete. Ask your administrator."
OPEN_DEAL = "A deal that lists the person is still open. Approve the request again once it is closed."
CLEARED = ("approver", "approved_on", "approved_plan_hash", "erasure_queued_at", "erasure_started_at")


class Refused(Exception):
	"""A check failed before anything was erased. `message` is safe to show: it holds no personal data."""

	def __init__(self, message: str):
		super().__init__(message)
		self.message = message


class BackOnHold(Exception):
	"""A deal now lists the person: the request went back On Hold and nothing was erased."""


def release_to_hold(doc) -> None:
	with server_write(frozen_ok=True):
		doc.update(dict.fromkeys(CLEARED))
		doc.update({"erasure_job_status": "", "erasure_error": None})
		doc.save(ignore_permissions=True)


def message_for(error: Exception) -> str:
	if isinstance(error, Refused):
		return error.message
	if isinstance(error, DncSecretUnavailableError):
		return _(SECRET_MISSING)
	return _(NOT_FINISHED)


def log_failure(request: str, text: str) -> None:
	"""The Error Log entry: the request number as the title, class names as the text. Never called while an
	exception is being handled (Sentry would read it), and never given a message."""
	frappe.log_error(request, text, reference_doctype=DOCTYPE, reference_name=request)


def write_failure(request: str, message: str) -> None:
	"""In a new transaction: the job Failed, the approval withdrawn, the status still Awaiting sign-off."""
	doc = frappe.get_doc(DOCTYPE, request)
	with server_write(frozen_ok=True):
		doc.update(dict.fromkeys(CLEARED))
		doc.update({"erasure_job_status": "Failed", "erasure_error": message})
		doc.save(ignore_permissions=True)


def fail(request: str, class_name: str, message: str, queued_messages: int) -> None:
	"""After the rollback. `class_name` and `message` are all that is left of the error. If recording the failure
	raises as well (a lock wait, a lost connection), the log names both classes and nothing else, and the request
	stays Running until the reaper fails it: the job never ends with an exception that carries the messages."""
	del frappe.local.message_log[queued_messages:]
	second = None
	try:
		write_failure(request, message)
	except Exception as error:
		second = type(error).__name__
	try:
		if second:
			frappe.db.rollback()
			log_failure(request, f"{class_name}; recording the failure raised {second}")
		else:
			log_failure(request, class_name)
		frappe.db.commit()
	except Exception:  # nothing more can be done here; the reaper recovers the request
		return


def after_commit(request: str, plan: ErasurePlan, ctx) -> None:
	"""The request is Erased and committed: now the bytes (RT-8), the search indexes and global search. Nothing here
	may undo it, and each step is its own transaction."""
	steps = (
		lambda: file_bytes.finish_pending(request),
		lambda: reindex(plan),
		lambda: scrub_search.resync(plan, ctx),
	)
	for step in steps:
		failed = None
		try:
			step()
			frappe.db.commit()
		except Exception as error:  # the hourly sweeper finishes the files; only the class name is logged
			failed = type(error).__name__
		if failed:
			frappe.db.rollback()
			log_failure(request, failed)


def reindex(plan: ErasurePlan) -> None:
	"""Re-index the records whose text changed, so the search index no longer holds her words."""
	from crm.search_sqlite import CRMSearch

	search = CRMSearch()
	if not (search.is_search_enabled() and search.index_exists()):
		return
	for doctype, kind in (
		("Comment", "comments"),
		("FCRM Note", "notes"),
		("Communication", "communications"),
	):
		for name in plan.targets[kind]:
			search.index_doc(doctype, name)
