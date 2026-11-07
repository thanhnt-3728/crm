# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Files and queued emails around a request (phase 06; RT-8, H1). Nothing here commits."""

import frappe

from crm.privacy.request_search import search_entries
from crm.privacy.request_visibility import DOCTYPE

FINISHED_MAIL = ("Sent", "Error", "Expired")


def delete_files(request: str, communications: list[str]) -> list[list]:
	"""Delete the File rows on the request and on its emails without any File hook (so no bytes go yet) and return
	what to do after the commit: the `[file_url, is_private]` pairs to delete and the search entries of the rows."""
	filters = [["attached_to_doctype", "=", DOCTYPE], ["attached_to_name", "=", request]]
	names = frappe.get_all("File", filters, pluck="name")
	if communications:
		names += frappe.get_all(
			"File",
			[["attached_to_doctype", "=", "Communication"], ["attached_to_name", "in", communications]],
			pluck="name",
		)
	pending = []
	rows = (
		frappe.get_all("File", {"name": ["in", names]}, ["file_url", "thumbnail_url", "is_private"])
		if names
		else []
	)
	for row in rows:
		for url in (row.file_url, row.thumbnail_url):
			if url and [url, row.is_private] not in pending:
				pending.append([url, row.is_private])
	if names:
		frappe.db.delete("File", {"name": ["in", names]})
	return pending + search_entries("File", names)


def unsent_mail(communications: list[str]) -> bool:
	"""Whether an email of the request is still waiting to go out (Not Sent, Sending, Partially Sent)."""
	return bool(communications) and bool(
		frappe.db.exists(
			"Email Queue", {"communication": ["in", communications], "status": ["not in", FINISHED_MAIL]}
		)
	)


def delete_mail_traces(request: str, communications: list[str], finished_only: bool = True) -> None:
	"""Queued emails about the request or sent as one of its emails (the outcome email holds her address and
	message) and the notification log rows about it. At close only a row that is done (Sent, Error, Expired) goes:
	an unsent one is somebody's answer. The purge deletes whatever is left (`finished_only=False`)."""
	status = {"status": ["in", FINISHED_MAIL]} if finished_only else {}
	queued = frappe.get_all(
		"Email Queue", {"reference_doctype": DOCTYPE, "reference_name": request, **status}, pluck="name"
	)
	if communications:
		queued += frappe.get_all(
			"Email Queue", {"communication": ["in", communications], **status}, pluck="name"
		)
	if queued:
		frappe.db.delete("Email Queue Recipient", {"parent": ["in", queued]})
		frappe.db.delete("Email Queue", {"name": ["in", queued]})
	frappe.db.delete("Notification Log", {"document_type": DOCTYPE, "document_name": request})
