# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The erasure job (design 5.6, phase 05; RT-1, RT-2, RT-6, RT-8, V1).

`run(request)` claims the job, checks the approver, the hold and the plan hash, applies the scrubbers in one
transaction (records, activities, files, history, misc, search, then late arrivals, then the rename last), blocks her
identifiers, writes the retained contract and checklist items and marks the request Erased. Any exception rolls
everything back and records a failure that holds no personal data. Bytes of deleted files go only after the commit.
"""

import json

import frappe
from frappe.utils import add_months, now_datetime, today

from crm.privacy.do_not_contact import add_entries
from crm.privacy.erasure import (
	scrub_activities,
	scrub_files,
	scrub_history,
	scrub_misc,
	scrub_names,
	scrub_records,
	scrub_search,
)
from crm.privacy.erasure.checklist_text import data_import_item, recording_item
from crm.privacy.erasure.executor_checks import claim, load_locked, preflight
from crm.privacy.erasure.executor_outcomes import BackOnHold, after_commit, fail, message_for
from crm.privacy.erasure.executor_passes import late_arrivals
from crm.privacy.erasure.plan import ErasurePlan
from crm.privacy.erasure.scrub_context import ScrubContext
from crm.privacy.request_status import ERASED, server_write
from crm.privacy.request_visibility import DOCTYPE

STEPS = (scrub_records, scrub_activities, scrub_files, scrub_history, scrub_misc, scrub_search)
# [RT-6] The rename is last, after the late-arrival pass, so every earlier step works with the docnames the plan was
# built from.
RENAME = scrub_names


def retain_contracts(doc, request: str, months: int) -> None:
	"""Her name and the contract reference, until counsel's retention period ends (design 5.11). The months are
	the ones in the approved plan, so a change after approval cannot shorten them."""
	person = " ".join((doc.requester_names or "").split())[:140]
	for row in doc.contract_references:
		frappe.get_doc(
			{
				"doctype": "CRM Retained Contract",
				"person_name": person,
				"contract_reference": row.reference,
				"delete_after": add_months(today(), months),
				"request": request,
			}
		).insert(ignore_permissions=True)


def pending_json(ctx: ScrubContext) -> str | None:
	"""What waits for the commit: file bytes `[url, is_private]` and global search rows `["search", doctype, name]`."""
	pending = [*ctx.pending_files, *(["search", doctype, name] for doctype, name in ctx.pending_search)]
	return json.dumps(pending) if pending else None


def finish(request: str, plan: ErasurePlan, ctx: ScrubContext) -> None:
	"""Step 10-11: block her identifiers, retain contracts, add the checklist items, mark the request Erased."""
	add_entries(
		[("email", v) for v in sorted(plan.identifiers.emails)]
		+ [("phone", v) for v in sorted(plan.identifiers.phones)]
	)
	doc = frappe.get_doc(DOCTYPE, request)  # fresh: the renames rewrote the match rows' record names
	retain_contracts(doc, request, plan.retention_months)
	have = {row.description for row in doc.checklist}
	items = [recording_item(p) for p in plan.recording_providers] + (
		[data_import_item(plan.data_imports)] if plan.data_imports else []
	)
	for text in items:
		if text not in have:
			doc.append("checklist", {"description": text, "auto_added": 1})
	doc.update(
		{
			"status": ERASED,
			"erased_on": now_datetime(),
			"erasure_job_status": "",
			"erasure_error": None,
			"pending_file_deletions": pending_json(ctx),
		}
	)
	with server_write(frozen_ok=True):
		doc.save(ignore_permissions=True)


def erase(request: str) -> tuple[ErasurePlan, ScrubContext]:
	plan = preflight(load_locked(request))
	ctx = ScrubContext(request, plan)
	for step in STEPS:
		step.scrub(plan, ctx)
	late_arrivals(request, plan, ctx, STEPS)
	RENAME.scrub(plan, ctx)
	finish(request, plan, ctx)
	return plan, ctx


def run(request: str) -> None:
	"""The background job. Claims the request, erases in one transaction, and records a clean failure otherwise.
	A failure is recorded after the `except` block has ended: only strings leave it, so neither Sentry nor a chained
	traceback can carry the original message (it may hold a docname such as a contact's name)."""
	if not claim(request):
		return
	queued_messages = len(frappe.local.message_log)
	frappe.flags.in_erasure = True
	held, failure, done = False, None, None
	try:
		try:
			done = erase(request)
		except BackOnHold:
			held = True
		except Exception as error:
			failure = (type(error).__name__, message_for(error))
		if failure:
			frappe.db.rollback()
			fail(request, *failure, queued_messages)
		else:
			frappe.db.commit()
			if not held:
				after_commit(request, *done)
	finally:
		frappe.flags.in_erasure = False
