# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Step 5: emails, calls, notes, tasks, comments and to-dos (design 5.6, RT-9, [I4]). The records stay; their text
becomes the content placeholder. Status, dates and assignees are kept."""

import frappe

from crm.privacy.erasure.plan import ErasurePlan
from crm.privacy.erasure.plan_activities import MAIL_COLUMNS
from crm.privacy.erasure.scrub_context import ScrubContext, blank, put
from crm.privacy.erasure.value_matcher import has_address, holds_her_value, replace_addresses, same_phone


def scrub_communications(plan: ErasurePlan, ctx: ScrubContext) -> None:
	"""Subject and content become the content placeholder; each of her addresses in sender, recipients, cc and bcc
	becomes the person placeholder and every other address stays. The same for every such email, whoever else is on it."""
	emails = plan.identifiers.emails
	names = [*plan.her_values.get("full_name", []), *plan.her_values.get("lead_name", [])]
	for name in plan.targets["communications"]:
		row = frappe.db.get_value("Communication", name, [*MAIL_COLUMNS, "sender_full_name"], as_dict=True)
		values = {"subject": ctx.content, "content": ctx.content, "text_content": ctx.content}
		for column in MAIL_COLUMNS:
			if has_address(row[column], emails):
				values[column] = replace_addresses(row[column], emails, ctx.person)
		if has_address(row.sender, emails) or holds_her_value(row.sender_full_name, plan.identifiers, names):
			values["sender_full_name"] = ctx.person
		put("Communication", name, values)


def scrub_call_logs(plan: ErasurePlan, ctx: ScrubContext) -> None:
	"""Her number in `from` or `to` becomes the placeholder and the recording URL is cleared."""
	for name in plan.targets["call_logs"]:
		row = frappe.db.get_value("CRM Call Log", name, ["from", "to"], as_dict=True)
		values = blank("recording_url")
		for column in ("from", "to"):
			if same_phone(row[column], plan.identifiers.phones):
				values[column] = ctx.person
		put("CRM Call Log", name, values)


def scrub_text(doctype: str, kind: str, fields: tuple, plan: ErasurePlan, ctx: ScrubContext) -> None:
	for name in plan.targets[kind]:
		put(doctype, name, dict.fromkeys(fields, ctx.content))


def scrub(plan: ErasurePlan, ctx: ScrubContext) -> None:
	scrub_communications(plan, ctx)
	scrub_call_logs(plan, ctx)
	scrub_text("FCRM Note", "notes", ("title", "content"), plan, ctx)
	scrub_text("CRM Task", "tasks", ("title", "description"), plan, ctx)
	scrub_text("ToDo", "todos", ("description",), plan, ctx)
	for name in plan.targets["comments"]:  # every type: Attachment and Info rows carry file names ([I4])
		subject = frappe.db.get_value("Comment", name, "subject")
		put("Comment", name, {"content": ctx.content, **({"subject": ctx.content} if subject else {})})
