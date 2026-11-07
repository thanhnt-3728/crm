# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Running the erasure job inline in a test (phase 05 part B).

The job commits at fixed points (claim, end, after a failure) and rolls back on error. A test cannot really
commit (it would keep the fixture), so `savepoint_transactions` turns `commit` into a savepoint and `rollback`
into "roll back to the last commit point": the same boundaries, undone by the test's final rollback.
"""

import os
from contextlib import contextmanager
from unittest.mock import patch

import frappe

from crm.api.erasure_review import approve_request
from crm.privacy.erasure.executor import run
from crm.privacy.tests.erasure_fixture import ErasureTestCase
from crm.privacy.tests.make_test_user import as_user

DOCTYPE = "CRM Erasure Request"
# Everything the erasure may touch, for "nothing changed" comparisons.
TABLES = (
	"CRM Lead", "CRM Deal", "CRM Contacts", "Contact", "Contact Email", "Contact Phone", "Address",
	"Dynamic Link", "Communication", "Communication Link", "CRM Call Log", "FCRM Note", "CRM Task", "Comment",
	"ToDo", "File", "Version", "Deleted Document", "CRM Notification", "Notification Log", "Email Queue",
	"Email Queue Recipient", "WA Message", "WA Profile", "Event Participants", "Failed Lead Sync Log",
	"CRM Do Not Contact", "CRM Retained Contract", "Activity Log", "Unhandled Email", "Event",
	"CRM Enrichment Run Change", "Route History",
)  # fmt: skip
# Tables with no `tab` prefix. `Error Log` is left out on purpose: a failed job writes one (request number and class).
RAW_TABLES = ("__global_search", "__UserSettings")


@contextmanager
def savepoint_transactions(request: str | None = None, events: list | None = None):
	"""`events` collects ("commit", status of the request) at each commit, so a test can say what happened
	before and after it. Like the real ones, `commit` runs the before/after-commit callbacks and `rollback`
	drops them unrun."""
	marks = []

	def mark():
		marks.append(f"job_commit_{len(marks)}")
		frappe.db.savepoint(marks[-1])

	def commit(*args, **kwargs):
		frappe.db.before_commit.run()
		mark()
		if events is not None:
			events.append(("commit", request and frappe.db.get_value(DOCTYPE, request, "status")))
		frappe.db.after_commit.run()

	def rollback(*args, **kwargs):
		if kwargs.get("save_point"):
			return real_rollback(**kwargs)
		frappe.db.before_commit.reset()
		frappe.db.after_commit.reset()
		real_rollback(save_point=marks[-1])
		frappe.db.value_cache.clear()
		if events is not None:
			events.append(("rollback", None))

	real_rollback = frappe.db.rollback
	mark()  # the state the job starts from
	frappe.realtime.clear_realtime_log()  # the fixture's messages are not the job's
	frappe.db.before_commit.reset()
	frappe.db.after_commit.reset()
	with patch.object(frappe.db, "commit", commit), patch.object(frappe.db, "rollback", rollback):
		yield marks


def snapshot(tables=TABLES) -> dict:
	"""Every row of the tables the erasure may touch, and what the request says matches (its child rows are
	rewritten, `modified` and all, by any save of the request, so only their meaning is compared)."""
	rows = {t: frappe.db.sql(f"select * from `tab{t}` order by name", as_list=True) for t in tables}
	for table in RAW_TABLES:
		rows[table] = frappe.db.sql(f"select * from `{table}` order by 1, 2", as_list=True)
	rows["matches"] = frappe.db.sql(
		"select reference_doctype, reference_name, confirmed, relation, is_source from `tabCRM Erasure Match` order by name",
		as_list=True,
	)
	return rows


def drain_search_queue() -> None:
	"""Frappe's global search queue lives in Redis, outside every rollback: stale items from other tests would be
	written by the first flush and look like changes."""
	while frappe.cache.rpop("global_search_queue"):
		pass


class ExecutorCase(ErasureTestCase):
	def setUp(self):
		super().setUp()
		drain_search_queue()
		self.addCleanup(self.forget_search_rows)

	def forget_search_rows(self):
		"""`__global_search` is MyISAM: the fixture's rows and the job's re-sync outlive the test's rollback."""
		person = f"Erased person {self.request}"
		keys = [("Contact", self.p.contact), ("Contact", self.p.colleague), ("Address", self.p.address)]
		keys += [("Contact", person), ("Address", person), ("Event", self.activity.misc.event)]
		keys += [("ToDo", self.activity.notes[k]) for k in self.activity.notes if k.startswith("todo_")]
		for doctype, name in keys:
			frappe.db.sql(
				"delete from `__global_search` where `doctype` = %s and `name` = %s", (doctype, name)
			)
		frappe.db.sql(  # the placeholders a name collision numbers (`-2`) are this request's own
			"delete from `__global_search` where `doctype` in ('Contact', 'Address') and `name` like %s",
			f"{person}-%",
		)

	def approve(self, user=None):
		return as_user(user or self.compliance, approve_request, self.request, self.request)

	def run_job(self, events: list | None = None):
		with savepoint_transactions(self.request, events):
			run(self.request)

	def approve_and_run(self):
		self.approve()
		self.run_job()

	def stored(self, *fields):
		return frappe.db.get_value(DOCTYPE, self.request, list(fields), as_dict=True)

	def values(self, doctype, name, *fields):
		return frappe.db.get_value(doctype, name, list(fields), as_dict=True)

	def on_disk(self):
		return [os.path.exists(path) for path in self.paths]
