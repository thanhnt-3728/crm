# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The approval screen's preview (design 5.6): what will be removed, what stays, what is still open, what needs a
human look. It is built from the same `ErasurePlan` the job executes, so it cannot promise what the job will not do.

Shape (phase 07 builds on it):
`{name, status, remove: [{kind, label, count, links: [{doctype, name, label}]}], keep: [{kind, text, count?}],
open_checklist: [{description, auto, predicted}], field_gaps: [{doctype, fieldname, label, fieldtype}],
identifier_hits: [{identifier, kind, records, communications, call_logs, count, capped, outside_her_records}],
needs_attention: [{kind, text, count}], blocked_by: [{doctype, name}]}`.
"""

import frappe
from frappe import _

from crm.privacy.erasure.checklist_text import data_import_item, recording_item
from crm.privacy.erasure.plan import KINDS, ErasurePlan
from crm.privacy.erasure.plan_builder import build_plan
from crm.privacy.erasure.preview_kinds import KIND_INFO, label_of
from crm.privacy.identifier_sync import identifier_impact
from crm.privacy.matching import find_by_email, find_by_phone

LINK_LIMIT = 50


def remove_section(plan: ErasurePlan) -> list[dict]:
	"""One entry per kind that has something to do, with the first `LINK_LIMIT` records behind it."""
	section = []
	for kind in KINDS:
		names = plan.targets[kind]
		if names:
			doctype, label = KIND_INFO[kind]
			links = [
				{"doctype": doctype, "name": n, "label": label_of(doctype, n)} for n in names[:LINK_LIMIT]
			]
			section.append({"kind": kind, "label": _(label), "count": len(names), "links": links})
	return section


def kept_on_removed_deals(plan: ErasurePlan) -> int:
	"""Notes, tasks, comments, to-dos and files of the open deals she was removed from: they stay."""
	deals = plan.targets["deals_removed"]
	if not deals:
		return 0
	rows = (
		("FCRM Note", {"reference_doctype": "CRM Deal", "reference_docname": ["in", deals]}),
		("CRM Task", {"reference_doctype": "CRM Deal", "reference_docname": ["in", deals]}),
		("Comment", {"reference_doctype": "CRM Deal", "reference_name": ["in", deals]}),
		("ToDo", {"reference_type": "CRM Deal", "reference_name": ["in", deals]}),
		("File", {"attached_to_doctype": "CRM Deal", "attached_to_name": ["in", deals], "is_folder": 0}),
	)
	return sum(frappe.db.count(doctype, filters) for doctype, filters in rows)


def keep_section(doc, plan: ErasurePlan) -> list[dict]:
	targets = plan.targets
	keep = [
		{"kind": "organizations", "text": _("Organizations: they are not the person")},
		{"kind": "deal_values", "text": _("Deal values, status, stage, owner, source and dates")},
		{
			"kind": "shells",
			"text": _("Leads and deals stay as anonymized records"),
			"count": len(targets["leads"]) + len(targets["deals_on"]) + len(targets["deals_copy"]),
		},
		{"kind": "emails_calls_notes", "text": _("Email, call and note records stay, with placeholder text")},
	]
	if plan.shared_addresses:  # [I3]
		text = _("Addresses shared with other people: only her link is removed, the address itself is kept")
		keep.append({"kind": "shared_addresses", "text": text, "count": len(plan.shared_addresses)})
	if count := kept_on_removed_deals(plan):
		text = _("Notes, tasks, comments and files of the open deals she was removed from")
		keep.append({"kind": "removed_deal_records", "text": text, "count": count})
	if doc.contract_references:
		text = _("Her name and the contract reference (signed contract exception)")
		keep.append({"kind": "retained_contract", "text": text, "count": len(doc.contract_references)})
	return keep


def checklist_section(doc, plan: ErasurePlan) -> list[dict]:
	"""Items still open on the request, and the ones the erasure will add."""
	items = [
		{"description": row.description, "auto": bool(row.auto_added), "predicted": False}
		for row in doc.checklist
		if not row.done
	]
	existing = {row.description for row in doc.checklist}
	predicted = []
	predicted.extend(recording_item(p) for p in plan.recording_providers)
	if plan.data_imports:
		predicted.append(data_import_item(plan.data_imports))
	return items + [
		{"description": text, "auto": True, "predicted": True} for text in predicted if text not in existing
	]


def hits_section(doc, plan: ErasurePlan) -> tuple[list[dict], list[tuple]]:
	"""Per kept identifier: what it reaches, and how many records outside the confirmed ones also hold it."""
	planned = {
		("CRM Deal", name)
		for kind in ("deals_on", "deals_copy", "deals_removed")
		for name in plan.targets[kind]
	}
	known = {(m.reference_doctype, m.reference_name) for m in doc.matches if m.confirmed} | planned
	hits, outside = [], set()
	for row in identifier_impact(doc, frappe.session.user):
		if row["excluded"]:
			continue
		finder = find_by_email if row["kind"] == "Email" else find_by_phone
		strays = {(h["doctype"], h["name"]) for h in finder(row["value"])} - known
		outside |= strays
		counts = (row["records"], row["communications"], row["call_logs"])
		hits.append(
			{
				"identifier": row["value"],
				"kind": row["kind"],
				"records": counts[0],
				"communications": counts[1],
				"call_logs": counts[2],
				"count": sum(counts),
				"capped": row["capped"],
				"outside_her_records": len(strays),
			}
		)
	return hits, sorted(outside)


def attention_section(plan: ErasurePlan, outside: list[tuple]) -> list[dict]:
	items = []
	if outside:
		text = _("Records that hold her details but are not confirmed in the request will not be erased")
		items.append({"kind": "outside_records", "text": text, "count": len(outside)})
	if plan.data_imports:
		items.append(
			{"kind": "data_import", "text": data_import_item(plan.data_imports), "count": plan.data_imports}
		)
	return items


def build_preview(doc) -> dict:
	plan = build_plan(doc, check_hold=False)
	hits, outside = hits_section(doc, plan)
	return {
		"name": doc.name,
		"status": doc.status,
		"remove": remove_section(plan),
		"keep": keep_section(doc, plan),
		"open_checklist": checklist_section(doc, plan),
		"field_gaps": plan.field_gaps,
		"identifier_hits": hits,
		"needs_attention": attention_section(plan, outside),
		"blocked_by": [{"doctype": "CRM Deal", "name": name} for name in plan.open_deals],
	}
