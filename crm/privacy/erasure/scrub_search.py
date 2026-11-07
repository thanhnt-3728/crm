# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Frappe's global search (`__global_search`) keeps the name, email and address of a contact, address, to-do or
event (review H3). The scrubbers write with `set_value`, which never touches it, and a rename does not rebuild it.

The table is MyISAM: a delete is immediate and a rollback cannot undo it, so nothing is deleted inside the erasure
transaction (a failed job must leave search as it was). Instead the rows to delete are listed on the request with
the file bytes (`pending_file_deletions`, written in the same transaction) and removed after the commit; the hourly
sweeper finishes them if the worker dies first. After the commit the queue is flushed (a pending item may still
hold her old text), the rows are deleted again, and the records that survive are re-synced under the names they
have now, so search finds them again without her words.
"""

import frappe
from frappe.utils import global_search

from crm.privacy.erasure.plan import ErasurePlan
from crm.privacy.erasure.scrub_context import ScrubContext
from crm.privacy.erasure.scrub_names import holds_her_name

NOT_SEARCHED = ("File",)  # deleted with the erasure: nothing to find again


def affected(plan: ErasurePlan) -> list[tuple[str, str]]:
	"""(doctype, old name) of every row whose search entry may hold her text."""
	rows = list(plan.docs())
	rows += [("Address", name) for name in plan.shared_addresses if holds_her_name(name, plan)]
	return rows


def purge(rows: list[tuple[str, str]]) -> None:
	by_doctype = {}
	for doctype, name in rows:
		by_doctype.setdefault(doctype, []).append(name)
	for doctype, names in by_doctype.items():
		frappe.db.sql(
			"delete from `__global_search` where `doctype` = %s and `name` in %s", (doctype, tuple(names))
		)


def scrub(plan: ErasurePlan, ctx: ScrubContext) -> None:
	"""Only list what to delete after the commit: the table cannot be rolled back."""
	ctx.pending_search.extend(affected(plan))


def resync(plan: ErasurePlan, ctx: ScrubContext) -> None:
	"""After the commit: no stale queued text, then the surviving records under the names they have now."""
	global_search.sync_global_search()
	purge(ctx.pending_search)
	for doctype, old in ctx.pending_search:
		name = ctx.renames.get((doctype, old), old)
		if doctype in NOT_SEARCHED or not frappe.db.exists(doctype, name):
			continue
		doc = frappe.get_doc(doctype, name)
		if doc.meta.get_global_search_fields():
			global_search.update_global_search(doc)
	global_search.sync_global_search()
