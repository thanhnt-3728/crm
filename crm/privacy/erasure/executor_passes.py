# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Rows that arrive while the job runs (review M1).

The plan is built once, at pre-flight, and only the request row is locked: a note, comment, to-do or email added to
her records by a rep, an automation or the mailbox afterwards would otherwise survive. Before the final commit the
targets are built again. What is new, apart from the rows the job wrote itself, is scrubbed in a second pass; if
a second look still finds something new, the job rolls back and fails with the generic text.
"""

import dataclasses

import frappe
from frappe import _

from crm.privacy.erasure.executor_outcomes import NOT_FINISHED, OPEN_DEAL, Refused
from crm.privacy.erasure.plan import KINDS, ErasureHoldError, ErasurePlan
from crm.privacy.erasure.plan_builder import build_plan
from crm.privacy.erasure.scrub_context import ScrubContext
from crm.privacy.request_visibility import DOCTYPE


def new_targets(request: str, seen: dict, ctx: ScrubContext) -> dict[str, list[str]]:
	"""Targets the plan built now holds that no earlier look found and the job did not write itself."""
	try:
		fresh = build_plan(frappe.get_doc(DOCTYPE, request))
	except ErasureHoldError:
		raise Refused(_(OPEN_DEAL)) from None
	new = {}
	for kind in KINDS:
		names = set(fresh.targets[kind]) - seen[kind] - set(ctx.created.get(kind, []))
		if names:
			new[kind] = sorted(names)
	return new


def late_arrivals(request: str, plan: ErasurePlan, ctx: ScrubContext, steps) -> None:
	"""Scrub what arrived since the plan was built; refuse if it keeps arriving."""
	seen = {kind: set(names) for kind, names in plan.targets.items()}
	new = new_targets(request, seen, ctx)
	if not new:
		return
	delta = dataclasses.replace(
		plan, targets={kind: new.get(kind, []) for kind in KINDS}, shared_addresses=[]
	)
	for step in steps:
		step.scrub(delta, ctx)
	for kind, names in new.items():
		seen[kind] |= set(names)
		plan.targets[kind] = sorted(set(plan.targets[kind]) | set(names))
	if new_targets(request, seen, ctx):
		raise Refused(_(NOT_FINISHED))
