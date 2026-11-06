# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
"""After the erasure commit: delete her disk files, re-index search, tell open forms to reload

Her File rows are deleted inside the transaction (`record_writes.delete_file_rows`; a file name
may spell her email); only the disk files they alone used are deleted here, after the commit, so
a rollback never leaves a row pointing at a deleted file. A file URL can spell her email too, so
the files still to delete are recorded PII-free: an HMAC-SHA256 of each one's site-relative path
(`public/files/x`, `private/files/x`), keyed with the site's encryption key and the request name,
in `outcome["pending_files"]` (a reader cannot confirm a guessed file name). `finish_files` hashes
what is on disk the same way and deletes the files whose hash is pending. The bench spike showed `delete_doc("File")`
adds an "Attachment Removed" comment naming the file and skips disk files without `content_hash`.
"""

import hashlib
import hmac
import json
import os

import frappe
from frappe.utils.file_manager import delete_file

from crm.erasure.shared_files import file_url_is_shared

REQUEST = "CRM Erasure Request"
SEARCH_QUEUE = "global_search_queue"
NOTIFIED_DOCTYPES = ("CRM Lead", "CRM Deal", "Contact")
# URL prefix -> folder under the site
SITE_FOLDERS = {"/files/": "public/files", "/private/files/": "private/files"}


def pending_hash(url: str, request_name: str) -> str | None:
	"""Keyed hash of the site-relative path of a site file URL; None for other URLs"""
	relative = _relative_path(url)
	return _keyed_hash(relative, request_name) if relative else None


def pending_hint(count: int, request_name: str) -> str:
	return f"{count} disk file(s) pending; run crm.erasure.post_commit.finish_files for {request_name}"


def delete_disk_files(urls: list[str], request_name: str) -> list[str]:
	"""Delete the site files `urls` (missing ones count as deleted); the pending hashes of failures"""
	failed = []
	for url in sorted(set(urls)):
		digest = pending_hash(url, request_name)
		if not digest:
			continue
		try:
			delete_file(url)
		except Exception:
			failed.append(digest)
	return failed


def finish_files(name: str) -> dict:
	"""Delete the disk files still pending for an Executed (or Closed) request; runbook / bench:

	`bench --site <site> execute crm.erasure.post_commit.finish_files --kwargs "{'name': 'CRM-ERQ-...'}"`
	"""
	request = frappe.get_doc(REQUEST, name)
	if request.status not in ("Executed", "Closed"):
		frappe.throw(f"{name} is {request.status}; files are deleted after it is Executed")
	outcome = json.loads(request.outcome or "{}")
	pending = set(outcome.get("pending_files") or [])
	still = []
	for relative, url in _site_files():
		digest = _keyed_hash(relative, name)
		if digest not in pending:
			continue
		if file_url_is_shared(url, []):  # uploaded again since: no longer hers alone
			continue
		try:
			delete_file(url)
		except Exception:
			still.append(digest)
	outcome["pending_files"] = still  # hashes not found on disk are gone already
	fields = {"outcome": json.dumps(outcome)}
	if not still:
		fields["last_error"] = None
	request.save_system_fields(**fields)
	frappe.db.commit()
	return {"files_deleted": len(pending) - len(still), "files_failed": len(still)}


def reindex_search(changes, ids) -> None:
	"""Re-index scrubbed records (their rows were deleted in the transaction); never raises

	The search queue may still hold snapshots of her records queued before the erasure (the
	scheduler syncs it every few minutes): those, and any queued row naming her, are dropped first.
	"""
	try:
		_drop_queued({*changes.reindex, *((doctype, old) for doctype, old, _new in changes.renamed)}, ids)
	except Exception:
		pass  # redis unavailable: nothing was queued that the sync below could write either
	reindex_records(changes.reindex)


def reindex_records(keys) -> None:
	"""Index `keys` [(doctype, name)] again (also after a failed run: MyISAM deletions stay)"""
	from frappe.utils.global_search import sync_global_search, update_global_search

	for doctype, name in keys:
		try:
			if frappe.get_meta(doctype).get_global_search_fields() and frappe.db.exists(doctype, name):
				update_global_search(frappe.get_doc(doctype, name))
		except Exception:
			continue  # search is a convenience: a record not re-indexed is simply not found by search
	try:
		sync_global_search()
	except Exception:
		pass  # the queue stays in redis: the scheduler's own sync indexes it later


def notify_and_clear_caches(keys) -> None:
	"""Drop cached copies of the changed records and tell open Lead/Deal/Contact forms to reload"""
	try:
		from frappe.model.document import clear_document_cache  # v16
	except ImportError:
		clear_document_cache = frappe.clear_document_cache  # v15
	for doctype, name in keys:
		try:
			clear_document_cache(doctype, name)
			if doctype in NOTIFIED_DOCTYPES:
				data = {"doctype": doctype, "name": name, "modified": str(frappe.db.get_value(doctype, name, "modified"))}
				frappe.publish_realtime("doc_update", data, doctype=doctype, docname=name)
		except Exception:
			continue  # a stale cache entry expires on its own; a form left open is a known limitation


def _drop_queued(keys: set[tuple[str, str]], ids) -> None:
	for value in frappe.cache.lrange(SEARCH_QUEUE, 0, -1) or []:
		try:
			item = json.loads(value)
		except ValueError:
			continue
		if (item.get("doctype"), item.get("name")) in keys or ids.matches_text(item.get("content")):
			frappe.cache.lrem(frappe.cache.make_key(SEARCH_QUEUE), 0, value)


def _keyed_hash(relative: str, request_name: str) -> str:
	"""HMAC-SHA256 keyed with the site's encryption key (v15 and v16) and the request name"""
	from frappe.utils.password import get_encryption_key

	key = f"{get_encryption_key()}:{request_name}".encode()
	return hmac.new(key, relative.encode(), hashlib.sha256).hexdigest()


def _relative_path(url: str | None) -> str | None:
	if not url or ".." in url.split("/"):
		return None
	for prefix, folder in SITE_FOLDERS.items():
		if url.startswith(prefix):
			return f"{folder}/{url[len(prefix):]}"
	return None


def _site_files():
	"""(site-relative path, file URL) of every file in the site's public and private files"""
	for prefix, folder in SITE_FOLDERS.items():
		root = frappe.get_site_path(*folder.split("/"))
		for directory, _dirs, files in os.walk(root):
			for file_name in files:
				inside = os.path.relpath(os.path.join(directory, file_name), root).replace(os.sep, "/")
				yield f"{folder}/{inside}", f"{prefix}{inside}"
