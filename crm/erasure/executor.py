# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
"""Apply the registry to an approved request's non-excluded matches, in registry order (F5, F6)

`run` does every database write of an erasure and nothing else: no commit, no file on disk (the
job commits, then `post_commit` deletes the disk files and re-indexes search). Person records are
anonymized in place, activity keeps its rows with the content marker, hidden copies are purged
or filtered. Writes are raw (see `record_writes`), so no Version row and no `modified` bump.
Re-running on an executed request changes nothing and reports no change. Last, her Contact and
Address are renamed away from her name (`record_renames`; allowed only inside the job).

A failure is raised as `ErasureStepFailed`, naming the registry doctype and exception class only.
"""

import frappe

from crm.erasure import hidden_copies, record_renames, record_writes
from crm.erasure import registry_model as model
from crm.erasure.discovery import installed
from crm.erasure.execution_context import Changes, Context, build_context
from crm.erasure.registry import REGISTRY

# Naming rules whose names never spell personal data (a Contact or Address is named after her)
SAFE_NAMING_RULES = ("Random", "Autoincrement", 'By "Naming Series" field', "Hash")
SAFE_AUTONAMES = ("hash", "autoincrement", "UUID")


class ErasureStepFailed(Exception):
	"""A registry step failed; the message carries no personal data"""

	def __init__(self, doctype: str, cause: BaseException):
		self.doctype, self.cause_class = doctype, type(cause).__name__
		super().__init__(f"{self.cause_class} while erasing {doctype}")


def run(request) -> Changes:
	ctx = build_context(request)
	changes = Changes()
	names_before = record_renames.her_names(ctx)  # read before her names are scrubbed
	for entry in REGISTRY:
		if not installed(entry):
			continue
		try:
			_apply(ctx, entry, changes)
		except Exception as e:
			raise ErasureStepFailed(entry.doctype, e) from e
	try:  # last: every step above found her records by their current names
		record_renames.rename_her_records(ctx, changes, names_before)
	except Exception as e:
		raise ErasureStepFailed("renamed records", e) from e
	changes.docs = _changed_person_docs(ctx, changes)
	return changes


def _apply(ctx: Context, entry: model.Entry, changes: Changes) -> None:
	if entry.kind == model.HIDDEN:
		hidden_copies.HANDLERS[entry.doctype](ctx, entry, changes)
	elif entry.kind == model.FILE:
		record_writes.delete_file_rows(ctx, entry, changes)  # disk files go after the commit
	elif not entry.match_rows:
		record_writes.scrub_link_titles(ctx, entry, changes)
	else:
		for name in sorted(ctx.matches.get(entry.doctype, ())):
			shared = ctx.actions.get((entry.doctype, name)) == model.UNLINK
			specs = record_writes.link_specs(entry) if shared else None
			record_writes.apply_fields(ctx, entry, name, changes, specs)


def _changed_person_docs(ctx: Context, changes: Changes) -> list[str]:
	"""Names of her person records for the outcome, only for doctypes whose names hold no data"""
	docs = []
	for entry in REGISTRY:
		if entry.kind == model.PERSON and changes.counts.get(entry.doctype) and _safe_names(entry.doctype):
			docs.extend(sorted(ctx.matches.get(entry.doctype, ())))
	return docs


def _safe_names(doctype: str) -> bool:
	meta = frappe.get_meta(doctype)
	if meta.istable:
		return False
	autoname = meta.autoname or ""
	return meta.naming_rule in SAFE_NAMING_RULES or autoname in SAFE_AUTONAMES or autoname.startswith("naming_series:")
