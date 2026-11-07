# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""What close and purge do to the emails and comments around a request (phase 06; RT-8, RT-12; design 5.8).

Emails attached to the request (the inbound mail of phase 04 and the outcome email sent from it) hold her address
and words, so they are scrubbed like any email of hers in phase 05 and then detached: nothing may link to the request
once it is closed. Files and queued mail are in `request_scrub_rows`, the global search rows in `request_search`.
Nothing here commits.
"""

import re
from types import SimpleNamespace

import frappe

from crm.privacy.erasure import scrub_activities
from crm.privacy.erasure.scrub_context import ScrubContext, put
from crm.privacy.erasure.value_matcher import Identifiers
from crm.privacy.placeholders import erased_content
from crm.privacy.request_scrub_rows import delete_files, delete_mail_traces
from crm.privacy.request_search import search_entries
from crm.privacy.request_visibility import DOCTYPE

NAME_SEPARATORS = re.compile(r"[\n;]+")


def requester_names(doc) -> list[str]:
	return [name.strip() for name in NAME_SEPARATORS.split(doc.requester_names or "") if name.strip()]


def request_communications(request: str) -> list[str]:
	return frappe.get_all(
		"Communication", {"reference_doctype": DOCTYPE, "reference_name": request}, pluck="name"
	)


def scrub_communications(doc, communications: list[str]) -> None:
	"""Subject and body become the content placeholder; each address of hers and her name become the person placeholder.

	Every identifier on the request counts here, excluded ones too (unlike design 5.6, which spares an excluded
	shared inbox): these emails exist only because of her request (phase 04 attaches mail by non-excluded identifiers
	alone) and their body is erased anyway, so the only loss is a shared address on a recipient line."""
	if not communications:
		return
	identifiers = Identifiers.of((row.kind, row.value) for row in doc.identifiers)
	plan = SimpleNamespace(
		identifiers=identifiers,
		her_values={"full_name": requester_names(doc), "lead_name": []},
		targets={"communications": communications},
	)
	scrub_activities.scrub_communications(plan, ScrubContext(doc.name, plan))


def detach_communications(request: str, communications: list[str]) -> None:
	"""Clear the link from each email to the request, and its timeline link rows."""
	if communications:
		put(
			"Communication",
			{"name": ["in", communications]},
			{"reference_doctype": None, "reference_name": None, "reference_owner": None},
		)
	frappe.db.delete("Communication Link", {"link_doctype": DOCTYPE, "link_name": request})


def scrub_comments(doc, communications: list[str]) -> None:
	"""Comments on the request and on its emails, of every type (an Attachment comment carries a file name):
	content erased, the rows and their authors kept."""
	content = erased_content(doc)
	filters = [["reference_doctype", "=", DOCTYPE], ["reference_name", "=", doc.name]]
	rows = frappe.get_all("Comment", filters, ["name", "subject"], as_list=True)
	if communications:
		on_emails = [["reference_doctype", "=", "Communication"], ["reference_name", "in", communications]]
		rows += frappe.get_all("Comment", on_emails, ["name", "subject"], as_list=True)
	for name, subject in rows:
		put("Comment", name, {"content": content, **({"subject": content} if subject else {})})


def delete_comments_on_emails(communications: list[str]) -> None:
	if communications:
		frappe.db.delete(
			"Comment", {"reference_doctype": "Communication", "reference_name": ["in", communications]}
		)


def scrub_request(doc) -> list[list]:
	"""Everything around the request, inside the caller's transaction. Returns what to do after the commit: file
	bytes to delete and global search rows to purge (`pending_file_deletions` entries)."""
	communications = request_communications(doc.name)
	scrub_communications(doc, communications)
	scrub_comments(doc, communications)
	pending = delete_files(doc.name, communications)
	delete_mail_traces(doc.name, communications)
	detach_communications(doc.name, communications)
	return pending + search_entries("Communication", communications)
