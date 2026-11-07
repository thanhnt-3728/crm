# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Step 4: her leads, contacts, addresses and the deals she is on (design 5.6). No renames here: the Contact and
Address docnames change last, in `scrub_names`."""

import frappe

from crm.privacy.erasure.plan import ErasurePlan
from crm.privacy.erasure.scrub_context import ScrubContext, blank, put
from crm.privacy.erasure.value_matcher import holds_her_value

ROW_FIELDS = ("full_name", "email", "mobile_no", "phone", "gender")  # fallback for CRM Contacts
# Words, not people: another contact's deal may say "Female" or "Office manager" too. Never matched by value on a deal.
CATEGORICAL = frozenset({"salutation", "gender", "job_title", "designation"})


def scrub_leads(plan: ErasurePlan, ctx: ScrubContext) -> None:
	"""Personal fields blanked, the mandatory name and the lead name become the placeholder."""
	fields = plan.personal_fields.get("CRM Lead", [])
	for name in plan.targets["leads"]:
		put("CRM Lead", name, {**blank(*fields), "first_name": ctx.person, "lead_name": ctx.person})


def scrub_contacts(plan: ErasurePlan, ctx: ScrubContext) -> None:
	fields = plan.personal_fields.get("Contact", [])
	for name in plan.targets["contacts"]:
		put("Contact", name, {**blank(*fields), "first_name": ctx.person, "full_name": ctx.person})
		for child in ("Contact Email", "Contact Phone"):
			frappe.db.delete(child, {"parent": name, "parenttype": "Contact"})


def scrub_addresses(plan: ErasurePlan, ctx: ScrubContext) -> None:
	"""Her own addresses are blanked. An address shared with someone else keeps its fields; only her link goes
	([I3]). Her contact's row on a shared address is deleted here, its docname is dealt with in `scrub_names`."""
	fields = plan.personal_fields.get("Address", [])
	for name in plan.targets["addresses"]:
		put("Address", name, {**blank(*fields), "address_title": ctx.person})
	if plan.shared_addresses and plan.targets["contacts"]:
		frappe.db.delete(
			"Dynamic Link",
			{
				"parenttype": "Address",
				"parent": ["in", plan.shared_addresses],
				"link_doctype": "Contact",
				"link_name": ["in", plan.targets["contacts"]],
			},
		)


def scrub_deals(plan: ErasurePlan, ctx: ScrubContext) -> None:
	"""Her row in the contacts table is anonymized (the link to the contact stays); the deal's own personal fields
	are blanked only where they hold her identifying values (her email, phone, name, social links), so another
	person's data copied from a different primary contact, and words she shares with them, are left alone. Values,
	status and stage are never touched."""
	row_fields = plan.personal_fields.get("CRM Contacts") or list(ROW_FIELDS)
	fields = [f for f in plan.personal_fields.get("CRM Deal", []) if f not in CATEGORICAL]
	for deal in [*plan.targets["deals_on"], *plan.targets["deals_copy"]]:
		rows = frappe.get_all(
			"CRM Contacts",
			{"parent": deal, "parenttype": "CRM Deal", "contact": ["in", plan.targets["contacts"]]},
			pluck="name",
		)
		for row in rows:
			put("CRM Contacts", row, {**blank(*row_fields), "full_name": ctx.person})
		if not fields:
			continue
		current = frappe.db.get_value("CRM Deal", deal, fields, as_dict=True)
		hers = [
			f for f in fields if holds_her_value(current[f], plan.identifiers, plan.her_values.get(f, ()))
		]
		put("CRM Deal", deal, blank(*hers))


def scrub(plan: ErasurePlan, ctx: ScrubContext) -> None:
	scrub_leads(plan, ctx)
	scrub_contacts(plan, ctx)
	scrub_addresses(plan, ctx)
	scrub_deals(plan, ctx)
