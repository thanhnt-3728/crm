# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
"""Frappe deduplicates uploads by content: several File rows can point at one file on disk

Phase 03 deletes her File rows, and the file on disk only when no other File row uses it.
"""

from collections.abc import Iterable

import frappe


def file_url_is_shared(file_url: str, matched_files: Iterable[str]) -> bool:
	"""True when a File row outside `matched_files` (File names) has the same `file_url`"""
	if not file_url:
		return False
	names = sorted(set(matched_files))
	filters = {"file_url": file_url}
	if names:
		filters["name"] = ["not in", names]
	return bool(frappe.db.exists("File", filters))
