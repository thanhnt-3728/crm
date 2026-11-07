# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Rename a Contact or Address to its placeholder inside the erasure transaction (phase 05 step 9 [RT-6]).

The step-0 spike (`test_rename_doc_rollback`) proved `rename_doc` on Frappe 16 writes only inside the open
transaction: it never commits, runs no DDL and enqueues nothing when called as below, and one rollback undoes it.
Two things it does leave to the caller, handled here:
- the list of doctypes a Dynamic Link column points at is cached for 12 hours and a raw-SQL row does not refresh
  it, so a stale cache would leave a row on her old name; the cache is dropped first;
- it writes an Info Comment `renamed from <old> to <new>` that names her; it is deleted;
- the links that cache the record's title (`link_title`) keep her old name, so they are reset to the placeholder.
"""

from contextlib import contextmanager

import frappe
from frappe.model.dynamic_links import _dynamic_link_map_key, get_dynamic_links
from frappe.model.rename_doc import rename_doc


def refresh_dynamic_link_cache() -> None:
	"""Forget which doctypes each Dynamic Link column points at, so the next rename looks at the table."""
	frappe.local.dynamic_link_map = None
	for field in get_dynamic_links():
		# the cache is keyed by the column that names the doctype, not by the link column
		frappe.cache.delete_value(_dynamic_link_map_key(field.parent, field.options))


TITLED_LINKS = ("Dynamic Link", "Communication Link")  # the link tables that store a copy of the title


def free_name(doctype: str, base: str) -> str:
	"""`base`, or `base-2`, `base-3`... when that docname is taken."""
	name, number = base, 1
	while frappe.db.exists(doctype, name):
		number += 1
		name = f"{base}-{number}"
	return name


@contextmanager
def muted_realtime():
	"""No realtime message while renaming: `doc_rename` and the Edit comment's update would push her old docname
	to every open browser. Nothing is stored; the messages are simply not sent."""
	real = frappe.publish_realtime
	frappe.publish_realtime = lambda *args, **kwargs: None
	try:
		yield
	finally:
		frappe.publish_realtime = real


def rename_to_placeholder(doctype: str, old: str, base: str) -> str:
	"""Rename `old` to `base` (or `base-2`... on collision) so every Link and Dynamic Link follows, with no side
	jobs and no trace of the old name in a Comment. Returns the new name. Writes nothing outside the transaction."""
	refresh_dynamic_link_cache()
	with muted_realtime():
		new = rename_doc(
			doctype,
			old,
			free_name(doctype, base),
			force=True,
			ignore_permissions=True,
			show_alert=False,
			rebuild_search=False,
		)
	frappe.db.delete(
		"Comment",
		{
			"reference_doctype": doctype,
			"reference_name": new,
			"comment_type": "Edit",
			"content": ["like", "renamed from %"],
		},
	)
	for table in TITLED_LINKS:
		frappe.db.set_value(
			table, {"link_doctype": doctype, "link_name": new}, "link_title", new, update_modified=False
		)
	return new
