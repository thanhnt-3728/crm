# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The records part of the plan: which leads, deals, contacts and addresses are hers, and how (design 5.6).

Read-only. A match row can point at a record that was deleted since (CRM Erasure Match is in
`ignore_links_on_delete`): it is skipped here and remembered in `gone`, so its Deleted Document is still found.
"""

from collections import defaultdict

import frappe

from crm.privacy.hold_rows import REMOVED
from crm.privacy.on_hold import OPEN_TYPES

LEAD, DEAL, CONTACT, ADDRESS = "CRM Lead", "CRM Deal", "Contact", "Address"
SETTINGS = "CRM Privacy Settings"


def personal_fields() -> dict[str, list[str]]:
	"""doctype -> fieldnames of the personal-fields list; a name this Frappe version no longer has is dropped."""
	fields = defaultdict(list)
	for row in frappe.get_single(SETTINGS).personal_fields:
		if frappe.get_meta(row.document_type).has_field(row.fieldname):
			fields[row.document_type].append(row.fieldname)
	return dict(fields)


def her_values(personal: dict, leads: list, contacts: list) -> dict[str, list[str]]:
	"""fieldname -> the values the personal fields hold on her confirmed lead and contact (trimmed, no repeats)."""
	values = defaultdict(set)
	for doctype, names in ((LEAD, leads), (CONTACT, contacts)):
		fields = personal.get(doctype, [])
		if not (names and fields):
			continue
		for row in frappe.get_all(doctype, {"name": ["in", names]}, fields):
			for fieldname in fields:
				value = row.get(fieldname)
				if isinstance(value, str) and value.strip():
					values[fieldname].add(value.strip())
	return {fieldname: sorted(found) for fieldname, found in values.items()}


def deals_listing(contacts: list) -> list[str]:
	if not contacts:
		return []
	Rows = frappe.qb.DocType("CRM Contacts")
	query = frappe.qb.from_(Rows).select(Rows.parent)
	return query.where((Rows.parenttype == DEAL) & Rows.contact.isin(contacts)).distinct().run(pluck=True)


def open_among(deals: list) -> list[str]:
	"""The deals whose status is of type Open, Ongoing or On Hold."""
	if not deals:
		return []
	open_statuses = set(frappe.get_all("CRM Deal Status", {"type": ["in", OPEN_TYPES]}, pluck="name"))
	rows = frappe.get_all(DEAL, {"name": ["in", deals]}, ["name", "status"])
	return sorted(row.name for row in rows if row.status in open_statuses)


def addresses_of(contacts: list) -> tuple[list[str], list[str]]:
	"""(addresses linked only to her contacts, addresses shared with someone or something else)."""
	if not contacts:
		return [], []
	Link = frappe.qb.DocType("Dynamic Link")
	hers = (
		frappe.qb.from_(Link)
		.select(Link.parent)
		.where((Link.parenttype == ADDRESS) & (Link.link_doctype == CONTACT) & Link.link_name.isin(contacts))
		.distinct()
		.run(pluck=True)
	)
	if not hers:
		return [], []
	rows = frappe.qb.from_(Link).select(Link.parent, Link.link_doctype, Link.link_name)
	rows = rows.where((Link.parenttype == ADDRESS) & Link.parent.isin(hers)).run()
	shared = {parent for parent, doctype, name in rows if not (doctype == CONTACT and name in contacts)}
	return sorted(set(hers) - shared), sorted(shared)


def collect(doc) -> frappe._dict:
	"""Classify the request's matches: confirmed leads and contacts, deals she is on (`deals_on`: confirmed),
	deals that only carry a copy of her contact (`deals_copy`, confirmed or not, RT-14), open deals she was removed
	from (`deals_removed`), addresses, deleted confirmed records (`gone`) and the open deals that forbid erasure."""
	confirmed, removed, gone = defaultdict(list), [], []
	for match in doc.matches:
		if not frappe.db.exists(match.reference_doctype, match.reference_name):
			if match.confirmed:
				gone.append((match.reference_doctype, match.reference_name))
		elif match.confirmed:
			confirmed[match.reference_doctype].append(match.reference_name)
		elif match.reference_doctype == DEAL and match.relation == REMOVED:
			removed.append(match.reference_name)
	deals_on = set(confirmed[DEAL])
	listing = set(deals_listing(confirmed[CONTACT]))
	copy = listing - deals_on
	addresses, shared = addresses_of(confirmed[CONTACT])
	return frappe._dict(
		leads=sorted(confirmed[LEAD]),
		contacts=sorted(confirmed[CONTACT]),
		deals_on=sorted(deals_on),
		deals_copy=sorted(copy),
		deals_removed=sorted(set(removed) - deals_on - listing),
		addresses=addresses,
		shared_addresses=shared,
		gone=sorted(gone),
		open_deals=open_among(sorted(deals_on | copy)),
	)
