# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Frappe's global search keeps the subject and sender of an email and the name of a file (`__global_search`).
Close and purge scrub or delete those rows, so the index has to forget them too, exactly as phase 05 does:

* the rows to purge are listed as `["search", doctype, name]` entries in `pending_file_deletions`, next to the file
  bytes, because the table is MyISAM: a delete cannot be rolled back, so it waits for the commit;
* after the commit the queue is flushed (a queued item may still hold the old text), the rows are purged, and the
  emails that survive are re-indexed under their placeholders.
"""

import frappe
from frappe.utils import global_search

from crm.privacy.erasure import file_bytes
from crm.privacy.erasure.scrub_search import purge

COMMUNICATION = "Communication"


def search_entries(doctype: str, names: list[str]) -> list[list]:
	return [["search", doctype, name] for name in names]


def searched_rows(pending: list) -> list[tuple[str, str]]:
	return [(entry[1], entry[2]) for entry in pending if len(entry) == 3 and entry[0] == "search"]


def finish_entries(pending: list) -> None:
	"""After the commit, for rows with no request left to list them on: delete the bytes and purge the search rows."""
	global_search.sync_global_search()
	file_bytes.delete_bytes(pending)
	purge(searched_rows(pending))


def resync_emails(pending: list) -> None:
	"""Index the emails that survived the close again: their text is now the placeholder."""
	for doctype, name in searched_rows(pending):
		if doctype == COMMUNICATION and frappe.db.exists(COMMUNICATION, name):
			doc = frappe.get_doc(COMMUNICATION, name)
			if doc.meta.get_global_search_fields():
				global_search.update_global_search(doc)
	global_search.sync_global_search()
