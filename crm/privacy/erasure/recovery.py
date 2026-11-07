# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Hourly recovery of the erasure job (phase 05; RT-7, RT-8).

`reap_stale_jobs` fails a job that never finished (a killed worker, a lost enqueue) so Compliance can approve again,
and finishes the file deletions a dead worker left on an Erased request. Each request is handled apart: one that
fails is logged (request number and exception class only) and the others still run. The scheduler commits.
"""

import frappe
from frappe import _
from frappe.utils import add_to_date, now_datetime

from crm.privacy import notify
from crm.privacy.erasure import file_bytes
from crm.privacy.erasure.approval import JOB_TIMEOUT
from crm.privacy.erasure.executor_outcomes import CLEARED
from crm.privacy.on_hold import _isolated
from crm.privacy.request_status import AWAITING, CLOSED, ERASED, server_write
from crm.privacy.request_visibility import DOCTYPE
from crm.privacy.roles import get_compliance_users

QUEUED_LIMIT_HOURS = 2
RUNNING_GRACE_MINUTES = 15
UNFINISHED = "Erasure job did not finish"


def stale_requests() -> list[str]:
	"""Awaiting sign-off requests whose Queued job is older than two hours, or whose Running job has outlived its
	timeout and a quarter hour."""
	now = now_datetime()
	queued_before = add_to_date(now, hours=-QUEUED_LIMIT_HOURS)
	running_before = add_to_date(now, seconds=-JOB_TIMEOUT, minutes=-RUNNING_GRACE_MINUTES)
	stale = frappe.get_all(
		DOCTYPE,
		filters={
			"status": AWAITING,
			"erasure_job_status": "Queued",
			"erasure_queued_at": ["<", queued_before],
		},
		pluck="name",
	)
	stale += frappe.get_all(
		DOCTYPE,
		filters={
			"status": AWAITING,
			"erasure_job_status": "Running",
			"erasure_started_at": ["<", running_before],
		},
		pluck="name",
	)
	return sorted(set(stale))


def fail_stale(request: str, queued_before, running_before) -> None:
	"""Fail one stuck job. The row lock waits for a job that is still finishing; a request that moved on meanwhile
	is left alone."""
	frappe.db.get_value(DOCTYPE, request, "name", for_update=True)
	doc = frappe.get_doc(DOCTYPE, request)
	queued = (
		doc.erasure_job_status == "Queued" and doc.erasure_queued_at and doc.erasure_queued_at < queued_before
	)
	running = (
		doc.erasure_job_status == "Running"
		and doc.erasure_started_at
		and doc.erasure_started_at < running_before
	)
	if doc.status != AWAITING or not (queued or running):
		return
	with server_write(frozen_ok=True):
		doc.update(dict.fromkeys(CLEARED))
		doc.update({"erasure_job_status": "Failed", "erasure_error": _(UNFINISHED)})
		doc.save(ignore_permissions=True)
	text = _("{0}: the erasure job did not finish. Approve the request again to retry.").format(request)
	notify.notify_users(
		get_compliance_users(), text, request=request, link_doctype=DOCTYPE, link_name=request
	)


def reap() -> None:
	now = now_datetime()
	queued_before = add_to_date(now, hours=-QUEUED_LIMIT_HOURS)
	running_before = add_to_date(now, seconds=-JOB_TIMEOUT, minutes=-RUNNING_GRACE_MINUTES)
	for request in stale_requests():
		with _isolated(request, request):
			fail_stale(request, queued_before, running_before)


def sweep_files() -> None:
	"""Erased and Closed requests whose bytes and search rows are still listed: delete them and clear the list
	(RT-8). A Closed request lists them too (phase 06: the close lists what its after-commit step must do)."""
	listed = frappe.get_all(
		DOCTYPE, {"status": ["in", [ERASED, CLOSED]], "pending_file_deletions": ["is", "set"]}, pluck="name"
	)
	for request in listed:
		with _isolated(request, request):
			file_bytes.finish_pending(request)


def reap_stale_jobs() -> None:
	"""The hourly job."""
	reap()
	sweep_files()
