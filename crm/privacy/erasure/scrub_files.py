# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Step 6: files on her records, deals she is on and her emails (design 5.6, RT-8).

The File rows are deleted with `frappe.db.delete` inside the transaction (no File hooks, so no bytes are removed
early) and each `(file_url, is_private)` is recorded in `ctx.pending_files`. The executor stores that list on the
request in the same transaction and deletes the bytes only after the commit; a rollback keeps rows and bytes.
"""

import frappe

from crm.privacy.erasure.plan import ErasurePlan
from crm.privacy.erasure.scrub_context import ScrubContext


def add_info_comment(doctype: str | None, name: str | None, text: str) -> str | None:
	"""A placeholder where the file was listed: an Info comment on the parent. Written without hooks."""
	if not (doctype and name and frappe.db.exists(doctype, name)):
		return None
	comment = frappe.get_doc(
		{
			"doctype": "Comment",
			"comment_type": "Info",
			"reference_doctype": doctype,
			"reference_name": name,
			"content": text,
		}
	)
	comment.name = frappe.generate_hash(length=10)
	comment.set_user_and_timestamp()
	comment.db_insert()
	return comment.name


def scrub(plan: ErasurePlan, ctx: ScrubContext) -> None:
	for name in plan.targets["files"]:
		row = frappe.db.get_value(
			"File",
			name,
			["file_url", "thumbnail_url", "is_private", "attached_to_doctype", "attached_to_name"],
			as_dict=True,
		)
		if not row:  # already gone: a re-run after a failure finds nothing to do
			continue
		for url in (row.file_url, row.thumbnail_url):
			if url and [url, row.is_private] not in ctx.pending_files:
				ctx.pending_files.append([url, row.is_private])
		frappe.db.delete("File", {"name": name})
		if comment := add_info_comment(row.attached_to_doctype, row.attached_to_name, ctx.file):
			ctx.created.setdefault("comments", []).append(comment)
