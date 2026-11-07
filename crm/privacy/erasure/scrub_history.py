# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Step 7: change history and the logs that copy record content (design 5.6, RT-4, plan additions; review H1, H4).

Version `data` is scrubbed by the rules of `version_scrub`: wholesale by field on her own lead, contact and addresses
and on the activities she is the subject of (notes, tasks, comments, to-dos, her emails' subject and content); only
by value everywhere else (deals, events, emails with other people on them), so a colleague's names, emails and
contact rows in a deal's history survive. Deleted Documents of hers are deleted. Activity Log and Unhandled Email
text becomes the content placeholder. The `_comments` cache column of her records is reset.
"""

import frappe

from crm.privacy.erasure.plan import ErasurePlan
from crm.privacy.erasure.scrub_context import ScrubContext, put
from crm.privacy.erasure.version_scrub import VersionRules, scrub_version

OWN = ("CRM Lead", "Contact", "Address")  # wholly hers: wiped by field
# Text fields wiped on the activities of hers whose Versions hold the old and new text.
TEXT_FIELDS = {
	"FCRM Note": ("title", "content"),
	"CRM Task": ("title", "description"),
	"ToDo": ("description",),
	"Comment": ("content", "subject"),
	"Communication": ("subject", "content", "text_content"),
	"File": ("file_name", "file_url", "thumbnail_url"),
	"Email Queue": ("message", "error", "attachments"),
}
CHILDREN = {"CRM Lead": (), "Contact": ("Contact Email", "Contact Phone"), "Address": ()}
ROW_FIELDS = ("full_name", "email", "mobile_no", "phone", "gender")  # fallback for CRM Contacts


def her_contact_rows(plan: ErasurePlan) -> set[str]:
	"""Names of the rows in a deal's contacts table that are her contact's."""
	if not plan.targets["contacts"]:
		return set()
	rows = frappe.get_all(
		"CRM Contacts", {"contact": ["in", plan.targets["contacts"]], "parenttype": "CRM Deal"}, pluck="name"
	)
	return set(rows)


def rules_for(doctype: str, plan: ErasurePlan, ctx: ScrubContext, her_rows: set[str]) -> VersionRules:
	"""Who owns a document decides how its history is scrubbed."""
	parts = frozenset(
		v for f in ("first_name", "middle_name", "last_name") for v in plan.her_values.get(f, [])
	)
	names = frozenset([*plan.her_values.get("full_name", []), *plan.her_values.get("lead_name", [])])
	base = {"identifiers": plan.identifiers, "placeholder": ctx.person, "names": names, "name_parts": parts}
	if doctype in OWN:
		fields = set(plan.personal_fields.get(doctype, []))
		for child in CHILDREN[doctype]:
			fields |= set(plan.personal_fields.get(child, []))
		return VersionRules(**base, field_wise=frozenset(fields))
	if doctype in TEXT_FIELDS:
		return VersionRules(**base, field_wise=frozenset(TEXT_FIELDS[doctype]))
	if doctype == "CRM Deal":
		row_fields = frozenset(plan.personal_fields.get("CRM Contacts") or ROW_FIELDS)
		contacts = set(plan.targets["contacts"])

		def hers(_table, row):
			return row.get("contact") in contacts or row.get("name") in her_rows

		return VersionRules(**base, row_fields=row_fields, her_rows=hers)
	return VersionRules(**base, mentions=doctype == "Event")


def scrub_versions(plan: ErasurePlan, ctx: ScrubContext) -> None:
	her_rows = her_contact_rows(plan)
	rules = {}
	for name in plan.targets["versions"]:
		doctype, data = frappe.db.get_value("Version", name, ["ref_doctype", "data"])
		if doctype not in rules:
			rules[doctype] = rules_for(doctype, plan, ctx, her_rows)
		new, changed = scrub_version(data, rules[doctype], ctx.person)
		if changed:
			put("Version", name, {"data": new})


def scrub_logs(plan: ErasurePlan, ctx: ScrubContext) -> None:
	for name in plan.targets["activity_logs"]:
		put("Activity Log", name, {"subject": ctx.content, "content": ctx.content})
	for name in plan.targets["unhandled_emails"]:
		put("Unhandled Email", name, {"raw": ctx.content})


def reset_comment_cache(plan: ErasurePlan) -> None:
	"""`_comments` holds snippets of the comments just erased: the leads, contacts and deals she is on."""
	for doctype, kind in (("CRM Lead", "leads"), ("Contact", "contacts"), ("CRM Deal", "deals_on")):
		for name in plan.targets[kind]:
			put(doctype, name, {"_comments": "[]"})


def scrub(plan: ErasurePlan, ctx: ScrubContext) -> None:
	scrub_versions(plan, ctx)
	if plan.targets["deleted_documents"]:
		frappe.db.delete("Deleted Document", {"name": ["in", plan.targets["deleted_documents"]]})
	scrub_logs(plan, ctx)
	reset_comment_cache(plan)
