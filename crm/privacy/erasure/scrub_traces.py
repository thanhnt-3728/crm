# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Step 8, part 2: the traces of her that are not records (review M4, L6): the text of events that name her, the
route history of her contact and address pages, and the saved list filters that hold her identifiers."""

import re

import frappe

from crm.privacy.erasure.plan import ErasurePlan
from crm.privacy.erasure.scrub_context import ScrubContext, put
from crm.privacy.erasure.scrub_json import blank_identifiers
from crm.privacy.erasure.text_mentions import mentions_identifier


def names_her(text: str | None, plan: ErasurePlan) -> bool:
	"""Whether a text mentions one of her identifiers or her full name as whole words."""
	if not text:
		return False
	if mentions_identifier(text, plan.identifiers):
		return True
	names = [*plan.her_values.get("full_name", []), *plan.her_values.get("lead_name", [])]
	return any(re.search(rf"(?<!\w){re.escape(n)}(?!\w)", text, re.IGNORECASE) for n in names if n.strip())


def scrub_events(plan: ErasurePlan, ctx: ScrubContext) -> None:
	"""An event she is invited to keeps its time and its other guests; its subject and description become the
	content placeholder where they name her."""
	for name in plan.targets["events"]:
		subject, description = frappe.db.get_value("Event", name, ["subject", "description"])
		values = {
			field: ctx.content
			for field, text in (("subject", subject), ("description", description))
			if names_her(text, plan)
		}
		put("Event", name, values)


def scrub_browser_traces(plan: ErasurePlan, ctx: ScrubContext) -> None:
	if plan.targets["route_history"]:
		frappe.db.delete("Route History", {"name": ["in", plan.targets["route_history"]]})
	for key in plan.targets["user_settings"]:
		user, doctype = key.split("::", 1)
		query = "select `data` from `__UserSettings` where `user` = %s and `doctype` = %s"
		data = (frappe.db.sql(query, (user, doctype)) or [[None]])[0][0]
		new = blank_identifiers(data, plan.identifiers, ctx.person)
		frappe.db.sql(
			"update `__UserSettings` set `data` = %s where `user` = %s and `doctype` = %s",
			(new, user, doctype),
		)


def scrub(plan: ErasurePlan, ctx: ScrubContext) -> None:
	scrub_events(plan, ctx)
	scrub_browser_traces(plan, ctx)
