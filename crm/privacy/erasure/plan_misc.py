# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The rows outside the CRM records that name her, and the notices about the request itself (design 5.6, RT-10).

Read-only. Free text is matched by whole value: a SQL `LIKE` prefilters, `text_mentions` decides (RT-4). Rows the
privacy module wrote about this request (the On Hold owner notices) are `hold_*` targets: they are deleted, not
scrubbed, and kept apart from her own rows.
"""

import frappe

from crm.privacy.erasure.plan_queries import by_reference, like_candidates, present
from crm.privacy.erasure.text_mentions import mentions_identifier, mentions_number, prefilter_terms
from crm.privacy.erasure.value_matcher import Identifiers, holds_her_value, holds_identifier, same_phone
from crm.privacy.identifiers import PHONE_REGION
from crm.privacy.matching import digits_only
from crm.privacy.placeholders import erased_content
from crm.utils import phone_search_digits

REQUEST = "CRM Erasure Request"


def mentioning(doctype: str, fields: list[str], ids: Identifiers, **filters) -> set[str]:
	"""Rows of `doctype` where one of the text fields holds one of her identifiers as a whole address or number."""
	if not present(doctype):
		return set()
	rows = like_candidates(doctype, fields, prefilter_terms(ids), **filters)
	return {row.name for row in rows if any(mentions_identifier(row[field], ids) for field in fields)}


def numbered(doctype: str, fields: list[str], request: str) -> set[str]:
	"""Rows whose text names this request's number as a whole token. A row the erasure already scrubbed says
	"Content erased PDR-n": that is her row with its text replaced, not a notice about the request."""
	rows = like_candidates(doctype, fields, [request])
	scrubbed = erased_content(request)
	return {
		row.name
		for row in rows
		if any(row[f] != scrubbed and mentions_number(row[f], request) for f in fields)
	}


def child_rows(child: str, parent_type: str, column: str, **conditions) -> set[str]:
	"""`column` (name or parent) of the child rows of `parent_type` that match the conditions (a list means any of)."""
	Row = frappe.qb.DocType(child)
	query = frappe.qb.from_(Row).select(Row[column]).where(Row.parenttype == parent_type)
	for field, value in conditions.items():
		query = query.where(Row[field].isin(value) if isinstance(value, list) else Row[field] == value)
	return set(query.run(pluck=True))


def hold_notices(request: str) -> dict[str, list[str]]:
	"""The owner notices the privacy module wrote about this request: CRM Notification, Notification Log, Email Queue."""
	notifications = set(
		frappe.get_all(
			"CRM Notification",
			{"notification_type_doctype": REQUEST, "notification_type_doc": request},
			pluck="name",
		)
	)
	notifications |= numbered("CRM Notification", ["message", "notification_text"], request)
	logs = set(
		frappe.get_all("Notification Log", {"document_type": REQUEST, "document_name": request}, pluck="name")
	)
	logs |= numbered("Notification Log", ["subject", "title", "description", "email_content"], request)
	queued = set(
		frappe.get_all("Email Queue", {"reference_doctype": REQUEST, "reference_name": request}, pluck="name")
	)
	queued |= numbered("Email Queue", ["message"], request)
	return {
		"hold_notifications": sorted(notifications),
		"hold_notification_logs": sorted(logs),
		"hold_emails": sorted(queued),
	}


def whatsapp(ids: Identifiers, main: dict) -> tuple[set[str], set[str]]:
	"""(WA Profiles, WA Messages) that are hers: her number or a link to her records, her messages' text."""
	if not present("WA Profile"):
		return set(), set()
	Profile = frappe.qb.DocType("WA Profile")
	profiles = set()
	for _phone, digits in ((p, phone_search_digits(p, region=PHONE_REGION)) for p in sorted(ids.phones)):
		query = frappe.qb.from_(Profile).select(Profile.name, Profile.phone_number)
		rows = query.where(digits_only(Profile.phone_number).like(f"%{digits}%")).run() if digits else []
		profiles |= {name for name, number in rows if same_phone(number, ids.phones)}
	for target, names in main.items():
		Link = frappe.qb.DocType("Dynamic Link")
		query = frappe.qb.from_(Link).select(Link.parent)
		if names:
			profiles |= set(
				query.where(
					(Link.parenttype == "WA Profile")
					& (Link.link_doctype == target)
					& Link.link_name.isin(names)
				).run(pluck=True)
			)
	Message = frappe.qb.DocType("WA Message")
	messages = set(by_reference("WA Message", "reference_doctype", "reference_docname", main))
	if profiles:
		messages |= set(frappe.get_all("WA Message", {"to": ["in", sorted(profiles)]}, pluck="name"))
	for number in sorted(ids.phones):  # the SQL prefilters on the digits (bounded); the number decides
		digits = phone_search_digits(number, region=PHONE_REGION)
		if digits:
			query = frappe.qb.from_(Message).select(Message.name, Message["from"])
			rows = query.where(digits_only(Message["from"]).like(f"%{digits}%")).run()
			messages |= {name for name, source in rows if same_phone(source, ids.phones)}
	messages |= mentioning("WA Message", ["message"], ids)
	return profiles, messages


def structured(ids: Identifiers, wanted: str, fields: list[str]) -> set[str]:
	"""Rows whose JSON text field holds one of her identifiers as a whole value, anywhere in it."""
	if not present(wanted):
		return set()
	found = set()
	for row in like_candidates(wanted, fields, prefilter_terms(ids)):
		for field in fields:
			try:
				document = frappe.parse_json(row[field] or "")
			except Exception:
				document = None
			if holds_identifier(document, ids):
				found.add(row.name)
	return found


def enrichment_changes(ids: Identifiers) -> set[str]:
	"""Rows of an enrichment run whose old or new value is one of her identifiers."""
	if not present("CRM Enrichment Run Change"):
		return set()
	rows = like_candidates("CRM Enrichment Run Change", ["old_value", "new_value"], prefilter_terms(ids))
	return {r.name for r in rows if holds_her_value(r.old_value, ids) or holds_her_value(r.new_value, ids)}


def email_queue(ids: Identifiers, main: dict, mails: list) -> set[str]:
	"""Queued mail to or from one of her addresses, about her records or emails, or whose text names her."""
	emails = sorted(ids.emails)
	found = set(by_reference("Email Queue", "reference_doctype", "reference_name", main))
	if mails:
		found |= set(frappe.get_all("Email Queue", {"communication": ["in", mails]}, pluck="name"))
	if emails:
		found |= set(frappe.get_all("Email Queue", {"sender": ["in", emails]}, pluck="name"))
		found |= child_rows("Email Queue Recipient", "Email Queue", "parent", recipient=emails)
	return found | mentioning("Email Queue", ["message"], ids)


def notifications(ids: Identifiers, main: dict, wa_messages: set) -> tuple[set[str], set[str]]:
	"""(CRM Notification, Notification Log) rows about her records or her messages, or whose text names her."""
	about = {**main, "WA Message": sorted(wa_messages)}
	crm = set(by_reference("CRM Notification", "reference_doctype", "reference_name", about))
	crm |= mentioning("CRM Notification", ["message", "notification_text"], ids)
	logs = set(by_reference("Notification Log", "document_type", "document_name", main))
	logs |= set(by_reference("Notification Log", "source_doctype", "source_name", main))
	logs |= mentioning("Notification Log", ["subject", "title", "description", "email_content"], ids)
	return crm, logs


def event_participants(ids: Identifiers, main: dict) -> set[str]:
	found = (
		child_rows("Event Participants", "Event", "name", email=sorted(ids.emails)) if ids.emails else set()
	)
	for target, names in main.items():
		if names:
			found |= child_rows(
				"Event Participants", "Event", "name", reference_doctype=target, reference_docname=names
			)
	return found


def misc_targets(ids: Identifiers, main: dict, mails: list, request: str) -> dict[str, list[str]]:
	"""Every `MISC` and `NOTICES` kind of the plan. `main` is the scope of her records (leads, contacts, deals she
	is on); `mails` her emails. The request's own notices are taken out of her rows: they are deleted, not scrubbed."""
	notices = hold_notices(request)
	profiles, wa_messages = whatsapp(ids, main)
	crm, logs = notifications(ids, main, wa_messages)
	return {
		"crm_notifications": sorted(crm - set(notices["hold_notifications"])),
		"notification_logs": sorted(logs - set(notices["hold_notification_logs"])),
		"email_queues": sorted(email_queue(ids, main, mails) - set(notices["hold_emails"])),
		"wa_messages": sorted(wa_messages),
		"wa_profiles": sorted(profiles),
		"event_participants": sorted(event_participants(ids, main)),
		"failed_sync_logs": sorted(structured(ids, "Failed Lead Sync Log", ["lead_data"])),
		"enrichment_changes": sorted(enrichment_changes(ids)),
		"activity_logs": sorted(mentioning("Activity Log", ["subject", "content"], ids)),
		"unhandled_emails": sorted(mentioning("Unhandled Email", ["raw"], ids)),
		**notices,
	}
