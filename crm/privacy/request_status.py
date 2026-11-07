# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Status machine of CRM Erasure Request and the "the server is writing" flag (design 5.2).

Status, the approval fields and the child tables are server-owned: the controller refuses a change
to them unless it was made inside `server_write()`. Only API functions and jobs open that block, so
a generic `frappe.client.save` can never move a request or confirm a match.
"""

from contextlib import contextmanager
from contextvars import ContextVar

import frappe
from frappe import _

LOGGED = "Logged"
AWAITING = "Awaiting sign-off"
ON_HOLD = "On Hold"
ERASED = "Erased"
DECLINED = "Declined"
CLOSED = "Closed"

STATUSES = (LOGGED, AWAITING, ON_HOLD, ERASED, DECLINED, CLOSED)
INITIAL_STATUS = LOGGED

# Awaiting sign-off -> Erased is allowed here but is reached only by the erasure job (phase 05).
ALLOWED = {
	LOGGED: {AWAITING, ON_HOLD, DECLINED},
	AWAITING: {ON_HOLD, DECLINED, ERASED},
	ON_HOLD: {AWAITING, DECLINED},
	ERASED: {CLOSED},
	DECLINED: {CLOSED},
	CLOSED: set(),
}

# Before the erasure a request may be edited. From Erased on it is a record: only server code writes it.
EDITABLE_STATUSES = (LOGGED, AWAITING, ON_HOLD)
FINISHED_STATUSES = (ERASED, DECLINED, CLOSED)

FROZEN_JOB_STATUSES = ("Queued", "Running")


def is_allowed(old: str | None, new: str | None) -> bool:
	return new in ALLOWED.get(old, ())


def assert_transition(old: str | None, new: str | None, denial_reason: str | None = None) -> None:
	"""Raise frappe.ValidationError unless `old` -> `new` is a permitted move. Declining needs a written reason."""
	if not is_allowed(old, new):
		frappe.throw(_("A request cannot move from {0} to {1}").format(old, new))
	if new == DECLINED and not (denial_reason or "").strip():
		frappe.throw(_("A denial reason is required to decline a request"))


def assert_not_frozen(job_status: str | None) -> None:
	"""A request is frozen while its erasure job is queued or running: what was approved is what runs."""
	if job_status in FROZEN_JOB_STATUSES:
		frappe.throw(_("Erasure in progress"))


_server_write: ContextVar[bool] = ContextVar("erasure_request_server_write", default=False)
_frozen_ok: ContextVar[bool] = ContextVar("erasure_request_frozen_ok", default=False)


@contextmanager
def server_write(frozen_ok: bool = False):
	"""Mark the writes inside the block as made by the server (an API function or a job), which lets
	them change server-owned fields and finished requests. The block is not tied to one document: any
	CRM Erasure Request saved inside it is privileged, so keep it narrow. `frozen_ok=True` is for the erasure executor and the stale-job
	reaper only: it also lets them write while the job is Queued or Running."""
	write_token = _server_write.set(True)
	frozen_token = _frozen_ok.set(frozen_ok)
	try:
		yield
	finally:
		_frozen_ok.reset(frozen_token)
		_server_write.reset(write_token)


def is_server_write() -> bool:
	return _server_write.get()


def is_frozen_ok() -> bool:
	return _frozen_ok.get()
