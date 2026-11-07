# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""File bytes are outside the transaction (RT-8): their rows are deleted with the erasure, the bytes only after the
commit, and what a dead worker left behind is finished by the hourly sweeper. Both use this module."""

import json
import os

import frappe

from crm.privacy.erasure.scrub_search import purge
from crm.privacy.request_visibility import DOCTYPE

FOLDERS = (("/private/files/", "private"), ("/files/", "public"))


def path_of(url: str | None, is_private=None) -> str | None:
	"""Where the bytes of a site-local File URL live, or None. Only `/files/...` and `/private/files/...` count (no
	scheme, no host, no way out of the folder); the folder follows the URL's prefix, not the `is_private` flag."""
	for prefix, folder in FOLDERS:
		if (url or "").startswith(prefix):
			base = os.path.realpath(frappe.get_site_path(folder, "files"))
			path = os.path.realpath(os.path.join(base, url[len(prefix) :]))
			return path if path.startswith(base + os.sep) else None
	return None


def delete_bytes(pending: list) -> None:
	"""Delete each `[file_url, is_private]` unless another File row still uses the URL (files with the same
	content share their bytes) or the URL points outside the files folders."""
	for url, is_private in (entry for entry in pending if len(entry) == 2):
		path = path_of(url, is_private)
		if path and not frappe.db.exists("File", {"file_url": url}) and os.path.isfile(path):
			os.remove(path)


def pending_of(request: str) -> list:
	raw = frappe.db.get_value(DOCTYPE, request, "pending_file_deletions")
	try:
		return json.loads(raw) if raw else []
	except ValueError:
		return []


def finish_pending(request: str) -> None:
	"""Delete the bytes and the global search rows listed on the request and clear the list. Safe to repeat."""
	pending = pending_of(request)
	delete_bytes(pending)
	purge([(entry[1], entry[2]) for entry in pending if len(entry) == 3 and entry[0] == "search"])
	frappe.db.set_value(DOCTYPE, request, "pending_file_deletions", None, update_modified=False)
