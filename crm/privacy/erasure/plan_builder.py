# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Build the erasure plan of a request (design 5.6). Read-only: nothing is written, so the approval screen, the
approval itself and the job can all call it and see the same thing.

`build_plan(doc)` raises `ErasureHoldError` when a deal she is still on is open (RT-2); the approval screen asks for
`check_hold=False` to show the plan and name the open deals instead.
"""

import frappe
from frappe import _

from crm.privacy.erasure import plan_activities as activity
from crm.privacy.erasure.plan import ErasureHoldError, ErasurePlan
from crm.privacy.erasure.plan_history import deleted_documents, versions
from crm.privacy.erasure.plan_misc import misc_targets
from crm.privacy.erasure.plan_records import CONTACT, DEAL, LEAD, collect, her_values, personal_fields
from crm.privacy.erasure.plan_traces import events_of, recording_providers, route_history, user_settings
from crm.privacy.erasure.value_matcher import Identifiers

# Custom fields of these types can hold a person's text; one off the personal-fields list is a gap (design 5.6).
TEXT_TYPES = ("Data", "Small Text", "Text", "Long Text", "Phone", "Attach", "Attach Image", "Text Editor")
GAP_DOCTYPES = (LEAD, DEAL, CONTACT)


def field_gaps(personal: dict) -> list[dict]:
	"""Custom fields on a lead, deal or contact that hold text and are not on the personal-fields list."""
	gaps = []
	for doctype in GAP_DOCTYPES:
		fields = frappe.get_all(
			"Custom Field",
			{"dt": doctype, "fieldtype": ["in", TEXT_TYPES]},
			["fieldname", "label", "fieldtype"],
		)
		gaps += [
			{"doctype": doctype, **field}
			for field in fields
			if field.fieldname not in personal.get(doctype, [])
		]
	return gaps


def data_imports() -> int:
	"""Data Imports of leads, deals or contacts: the file may hold her row, and the CRM does not read it."""
	return frappe.db.count("Data Import", {"reference_doctype": ["in", list(GAP_DOCTYPES)]})


def build_plan(doc, *, check_hold: bool = True) -> ErasurePlan:
	ids = Identifiers.of((row.kind, row.value) for row in doc.identifiers if not row.excluded)
	records = collect(doc)
	if check_hold and records.open_deals:
		frappe.throw(_("A deal that lists the person is still open"), ErasureHoldError)
	personal = personal_fields()
	main = {LEAD: records.leads, CONTACT: records.contacts, DEAL: records.deals_on}
	mails = activity.communications(ids, main)
	calls = activity.call_logs(ids, main)
	traces = misc_targets(ids, main, mails, doc.name)
	traces["events"] = events_of(traces["event_participants"])
	traces["route_history"] = route_history([*records.contacts, *records.addresses])
	traces["user_settings"] = user_settings(ids)
	images = activity.images(records.leads, records.contacts)
	plan = ErasurePlan(doc.name, ids)
	plan.targets.update(
		{
			**{
				kind: records[kind]
				for kind in ("leads", "deals_on", "deals_copy", "deals_removed", "contacts", "addresses")
			},
			"communications": mails,
			"call_logs": calls,
			"notes": activity.notes(main, calls),
			"tasks": activity.tasks(main),
			"comments": activity.comments(main),
			"todos": activity.todos(main),
			"files": activity.files(main, mails, images, traces["wa_messages"]),
			**traces,
		}
	)
	plan.targets["versions"] = versions(plan.docs())
	plan.targets["deleted_documents"] = deleted_documents(ids, plan.docs(), records.gone, main)
	plan.personal_fields = personal
	plan.her_values = her_values(personal, records.leads, records.contacts)
	plan.gone = records.gone
	plan.open_deals = records.open_deals
	plan.shared_addresses = records.shared_addresses
	plan.recording_providers = recording_providers(calls)
	plan.retention_months = (
		frappe.db.get_single_value("CRM Privacy Settings", "contract_retention_months") or 0
	)
	plan.data_imports = data_imports()
	plan.field_gaps = field_gaps(personal)
	return plan
