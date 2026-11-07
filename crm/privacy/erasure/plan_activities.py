# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The activities part of the plan: emails, calls, notes, tasks, comments, to-dos and files (design 5.6, RT-9).

Read-only. A row is hers when it hangs off her lead, contact or a deal she is on, or (emails, calls) when one of her
identifiers is a whole address or number in it. Emails and calls on a deal she was removed from are found only by the
identifier, never by the deal.
"""

import frappe

from crm.privacy.erasure.plan_queries import by_reference, child_parents, like_candidates
from crm.privacy.erasure.value_matcher import Identifiers, has_address, same_phone
from crm.privacy.identifiers import PHONE_REGION
from crm.privacy.matching import digits_only
from crm.utils import phone_search_digits

MAIL_COLUMNS = ("sender", "recipients", "cc", "bcc")


def communications(ids: Identifiers, scope: dict) -> list[str]:
	"""Emails linked by reference or timeline to her records, or with one of her addresses as sender, recipient,
	cc or bcc (a whole address of the list)."""
	found = set(by_reference("Communication", "reference_doctype", "reference_name", scope))
	found |= set(child_parents("Communication Link", "Communication", scope))
	for row in like_candidates("Communication", list(MAIL_COLUMNS), sorted(ids.emails)):
		if any(has_address(row[column], ids.emails) for column in MAIL_COLUMNS):
			found.add(row.name)
	return sorted(found)


def _numbers_of(phones) -> list[tuple[str, str]]:
	return [(phone, phone_search_digits(phone, region=PHONE_REGION)) for phone in sorted(phones)]


def call_logs(ids: Identifiers, scope: dict) -> list[str]:
	"""Calls linked to her records, or from/to one of her numbers in any format."""
	found = set(by_reference("CRM Call Log", "reference_doctype", "reference_docname", scope))
	found |= set(child_parents("Dynamic Link", "CRM Call Log", scope))
	Call = frappe.qb.DocType("CRM Call Log")
	for _phone, digits in _numbers_of(ids.phones):
		if not digits:
			continue
		pattern = f"%{digits}%"
		query = frappe.qb.from_(Call).select(Call.name, Call["from"], Call["to"])
		query = query.where(digits_only(Call["from"]).like(pattern) | digits_only(Call["to"]).like(pattern))
		found |= {
			name
			for name, source, target in query.run()
			if any(same_phone(n, ids.phones) for n in (source, target))
		}
	return sorted(found)


def notes(scope: dict, calls: list) -> list[str]:
	"""Notes on her records, and the notes her call logs point at."""
	found = set(by_reference("FCRM Note", "reference_doctype", "reference_docname", scope))
	if calls:
		found |= set(
			frappe.get_all("CRM Call Log", {"name": ["in", calls], "note": ["is", "set"]}, pluck="note")
		)
	return sorted(found)


def tasks(scope: dict) -> list[str]:
	return sorted(by_reference("CRM Task", "reference_doctype", "reference_docname", scope))


def comments(scope: dict) -> list[str]:
	"""Every Comment row on her records, whatever its type: Attachment and Info rows carry file names and
	addresses too ([I4])."""
	return sorted(by_reference("Comment", "reference_doctype", "reference_name", scope))


def todos(scope: dict) -> list[str]:
	return sorted(by_reference("ToDo", "reference_type", "reference_name", scope))


def files(scope: dict, mails: list, images: list, wa_messages: list | None = None) -> list[str]:
	"""Files attached to her records, her emails and her WhatsApp messages, and the files her `image` fields
	point at."""
	found = set(
		by_reference(
			"File",
			"attached_to_doctype",
			"attached_to_name",
			{**scope, "Communication": mails, "WA Message": wa_messages or []},
			is_folder=0,
		)
	)
	if images:
		found |= set(frappe.get_all("File", {"file_url": ["in", images], "is_folder": 0}, pluck="name"))
	return sorted(found)


def images(leads: list, contacts: list) -> list[str]:
	"""The `image` (photo) URLs on her lead and contact."""
	urls = []
	for doctype, names in (("CRM Lead", leads), ("Contact", contacts)):
		if names:
			urls += frappe.get_all(doctype, {"name": ["in", names], "image": ["is", "set"]}, pluck="image")
	return urls
