# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
"""Raw writes of the registry's field treatments onto one matched row

Only `frappe.db.set_value(..., update_modified=False)` and `frappe.db.delete`: no controller, no
hooks, no Version row, no `modified` bump. Each function writes only what differs from what is
stored, so a re-run changes nothing and reports nothing.
"""

import frappe

from crm.erasure import registry_model as model
from crm.erasure.scrub_actions import field_value
from crm.erasure.shared_files import file_url_is_shared

TABLE_TREATMENTS = (model.DELETE_ROWS, model.DROP_HER_LINKS)


def apply_fields(ctx, entry: model.Entry, name: str, changes, specs=None) -> bool:
	"""Apply `specs` (default: all of `entry.fields`) to row `name`; True when anything changed"""
	specs = entry.fields if specs is None else specs
	scalar = [spec for spec in specs if spec[1] not in TABLE_TREATMENTS]
	changed = _write_scalars(ctx, entry.doctype, name, scalar)
	for spec in specs:
		if spec[1] == model.DELETE_ROWS:
			changed |= bool(_delete_child_rows(entry.doctype, name, spec[0]))
		elif spec[1] == model.DROP_HER_LINKS:
			changed |= bool(_drop_her_links(ctx, entry.doctype, name, spec[0]))
	if changed:
		changes.add(entry.doctype)
	return changed


def delete_file_rows(ctx, entry: model.Entry, changes) -> None:
	"""Delete her File rows in the transaction (a file name may spell her email); the disk files
	they alone use go after the commit (`changes.files`). Raw: no "Attachment Removed" comment."""
	names = sorted(ctx.matches.get(entry.doctype, ()))
	for name in names:
		row = frappe.db.get_value("File", name, ["file_url", "thumbnail_url", "is_folder"], as_dict=True)
		if not row or row.is_folder:
			continue
		if not file_url_is_shared(row.file_url, names):
			changes.files.extend(url for url in (row.file_url, row.thumbnail_url) if url)
		frappe.db.delete("File", name)
		changes.add("File")


def link_specs(entry: model.Entry) -> tuple:
	"""The treatments of a shared record (an Address of several people): her link rows only"""
	return tuple(spec for spec in entry.fields if spec[1] == model.DROP_HER_LINKS)


def scrub_link_titles(ctx, entry: model.Entry, changes) -> None:
	"""link_title of link rows (Dynamic Link, Communication Link) pointing at her records"""
	treatment = dict((spec[0], spec[1]) for spec in entry.fields).get("link_title")
	marker = model.name_marker(ctx.request_name) if treatment == model.NAME_MARKER else None
	for doctype, name in sorted(ctx.her_records):
		rows = frappe.get_all(
			entry.doctype,
			filters={"link_doctype": doctype, "link_name": name, "link_title": ["is", "set"]},
			fields=["name", "parenttype", "parent", "link_title"],
		)
		names = [
			row.name
			for row in rows
			if row.link_title != marker and (row.parenttype, row.parent) not in ctx.excluded
		]
		if names:
			frappe.db.set_value(entry.doctype, {"name": ["in", names]}, "link_title", marker, update_modified=False)
			changes.add(entry.doctype, len(names))


def _write_scalars(ctx, doctype: str, name: str, specs) -> bool:
	if not specs:
		return False
	columns = sorted({spec[0] for spec in specs} | {spec[2] for spec in specs if len(spec) > 2})
	row = frappe.db.get_value(doctype, name, columns, as_dict=True)
	if not row:  # deleted since approval: nothing of hers left in it
		return False
	updates = {}
	for spec in specs:
		value = field_value(spec, row, ctx.ids, ctx.request_name)
		if (value or None) != (row.get(spec[0]) or None):
			updates[spec[0]] = value
	if updates:
		frappe.db.set_value(doctype, name, updates, update_modified=False)
	return bool(updates)


def _child_doctype(doctype: str, fieldname: str) -> str:
	return frappe.get_meta(doctype).get_field(fieldname).options


def _delete_child_rows(doctype: str, name: str, fieldname: str) -> int:
	filters = {"parenttype": doctype, "parent": name, "parentfield": fieldname}
	child = _child_doctype(doctype, fieldname)
	count = frappe.db.count(child, filters)
	if count:
		frappe.db.delete(child, filters)
	return count


def _drop_her_links(ctx, doctype: str, name: str, fieldname: str) -> int:
	child = _child_doctype(doctype, fieldname)
	rows = frappe.get_all(
		child,
		filters={"parenttype": doctype, "parent": name, "parentfield": fieldname},
		fields=["name", "link_doctype", "link_name"],
	)
	hers = [row.name for row in rows if (row.link_doctype, row.link_name) in ctx.her_records]
	if hers:
		frappe.db.delete(child, {"name": ["in", hers]})
	return len(hers)
