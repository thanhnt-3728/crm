# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
"""Rename her records whose names spell her name: Contact ("Marisol Reyes") and Address
("Marisol Reyes-Billing"), to the name marker ("Erased CRM-ERQ-2026-00001", then "-1", "-2", ...)

`frappe.rename_doc` rewrites every Link and Dynamic Link column (CRM Deal.contact, CRM Contacts,
Dynamic Link, Communication Link, ToDo, File.attached_to_name, Version.docname, ...). The bench
check showed it neither commits nor runs DDL for these doctypes, so it stays inside the erasure
transaction. Afterwards the "renamed from <old> to <new>" Comment it adds is deleted, the
request's match rows follow (`rewrite_references`; Address has no after_rename hook), and Version
entries of Link fields to the renamed doctype are rewritten. A shared Address (only unlinked) is renamed and
retitled only when titled after her (its title equals, or its name starts with, one of her names
read before the erasure: Contact full_name, Lead/Deal lead_name); the colleague's links stay. Records already carrying the marker are skipped, so a re-run renames nothing.
Runs only inside the job (`jobs.running_erasure`): the rename guard refuses it anywhere else.
"""

import json

import frappe
from frappe.model.rename_doc import rename_doc

from crm.erasure import registry_model as model
from crm.fcrm.doctype.crm_erasure_request.erasure_request_references import rewrite_references

RENAMED_DOCTYPES = ("Contact", "Address")
# Where her name stood before the erasure scrubbed it: a shared Address titled after her is hers to retitle
NAME_SOURCES = (("Contact", "full_name"), ("CRM Lead", "lead_name"), ("CRM Deal", "lead_name"))


def her_names(ctx) -> set[str]:
	"""Her names as stored before the erasure (read before any scrub runs)"""
	names = set()
	for doctype, field in NAME_SOURCES:
		matched = sorted(ctx.matches.get(doctype, ()))
		if matched:
			values = frappe.get_all(doctype, {"name": ["in", matched]}, pluck=field)
			names.update(value.strip() for value in values if value and value.strip())
	return names


def rename_her_records(ctx, changes, names_before: set[str]) -> None:
	marker = model.name_marker(ctx.request_name)
	for doctype in RENAMED_DOCTYPES:
		for old in sorted(ctx.matches.get(doctype, ())):
			if _is_marker_name(old, marker) or not frappe.db.exists(doctype, old):
				continue
			if ctx.actions.get((doctype, old)) == model.UNLINK:
				if not _titled_after_her(doctype, old, names_before):
					continue  # shared and not titled after her: not hers to rename
				frappe.db.set_value(doctype, old, "address_title", marker, update_modified=False)
			_rename(changes, doctype, old, _free_name(doctype, marker))
	for _doctype, old, _new in changes.renamed:
		_drop_orphan_series(_doctype, old)
	renamed = {(doctype, old): new for doctype, old, new in changes.renamed}
	reindex = [(doctype, renamed.get((doctype, name), name)) for doctype, name in changes.reindex]
	changes.reindex = list(dict.fromkeys([*reindex, *((d, new) for d, _old, new in changes.renamed)]))


def _rename(changes, doctype: str, old: str, new: str) -> None:
	rename_doc(  # the model function: frappe.rename_doc has no ignore_permissions
		doctype=doctype,
		old=old,
		new=new,
		force=True,
		merge=False,
		show_alert=False,
		ignore_permissions=True,
		rebuild_search=False,  # the job re-indexes her records itself after the commit
	)
	rewrite_references(doctype, old, new)
	_delete_rename_comments(doctype, old, new)
	_rewrite_version_values(doctype, old, new)
	frappe.db.delete("__global_search", {"doctype": doctype, "name": old})
	changes.renamed.append((doctype, old, new))
	changes.add("Renamed records")


def _titled_after_her(doctype: str, name: str, names_before: set[str]) -> bool:
	"""Deterministic, not a name search: the title equals one of her names, or the name starts with one"""
	title = (frappe.db.get_value(doctype, name, "address_title") or "").strip()
	# Address names are "<title>-<type>[-n]": a prefix counts only up to that dash
	return title in names_before or any(name == her or name.startswith(f"{her}-") for her in names_before)


def _is_marker_name(name: str, marker: str) -> bool:
	return name == marker or name.startswith(f"{marker}-")


def _free_name(doctype: str, marker: str) -> str:
	candidate, suffix = marker, 0
	while frappe.db.exists(doctype, candidate):
		suffix += 1
		candidate = f"{marker}-{suffix}"
	return candidate


def _delete_rename_comments(doctype: str, old: str, new: str) -> None:
	"""The "renamed from <old> to <new>" Comment, and any Version of it"""
	names = frappe.get_all(
		"Comment",
		{"reference_doctype": doctype, "reference_name": new, "comment_type": "Edit", "content": ["like", f"%{_like(old)}%"]},
		pluck="name",
	)
	if names:
		frappe.db.delete("Version", {"ref_doctype": "Comment", "docname": ["in", names]})
		frappe.db.delete("Comment", {"name": ["in", names]})


def _drop_orphan_series(doctype: str, old: str) -> None:
	"""Naming counters "<stem>-" spelling her name once no record of `doctype` uses the stem"""
	base, _dash, suffix = old.rpartition("-")
	for stem in {f"{old}-", *([f"{base}-"] if base and suffix.isdigit() else [])}:
		if not frappe.db.exists(doctype, {"name": ["like", f"{_like(stem)}%"]}):
			frappe.db.sql("delete from `tabSeries` where name = %s", (stem,))


def _rewrite_version_values(doctype: str, old: str, new: str) -> None:
	"""Version entries whose field is a Link to `doctype` holding `old` now hold `new`

	Only Link fields of the Version's own doctype (or of its child table, per row) count: a Data
	field that happens to equal the old name (a namesake's lead_name) is left alone.
	"""
	pattern = f"%{_like(json.dumps(old)[1:-1])}%"
	query = "select name, ref_doctype, data from `tabVersion` where data like %s"
	for name, ref_doctype, data in frappe.db.sql(query, (pattern,)):
		try:
			parsed = json.loads(data or "{}")
			replaced = _relink(parsed, frappe.get_meta(ref_doctype), doctype, old, new)
		except Exception:
			continue  # unreadable data or a removed doctype: nothing to follow
		if replaced != parsed:
			frappe.db.set_value("Version", name, "data", frappe.as_json(replaced), update_modified=False)


def _relink(data: dict, meta, target: str, old: str, new: str) -> dict:
	def swap(value):
		return new if value == old else value

	def links(of_meta) -> set[str]:
		return {df.fieldname for df in of_meta.fields if df.fieldtype == "Link" and df.options == target}

	def child_links(table: str) -> set[str]:
		field = meta.get_field(table)
		return links(frappe.get_meta(field.options)) if field and field.options else set()

	own = links(meta)
	out = dict(data)
	if isinstance(data.get("changed"), list):
		out["changed"] = [[e[0], *map(swap, e[1:])] if e and e[0] in own else e for e in data["changed"]]
	for key in ("added", "removed"):
		if isinstance(data.get(key), list):
			out[key] = [
				[e[0], {k: swap(v) if k in child_links(e[0]) else v for k, v in e[1].items()}]
				if len(e) > 1 and isinstance(e[1], dict)
				else e
				for e in data[key]
			]
	if isinstance(data.get("row_changed"), list):
		out["row_changed"] = [
			[*e[:3], [[c[0], *map(swap, c[1:])] if c and c[0] in child_links(e[0]) else c for c in e[3]]]
			if len(e) > 3 and isinstance(e[3], list)
			else e
			for e in data["row_changed"]
		]
	return out


def _like(value: str) -> str:
	return value.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
