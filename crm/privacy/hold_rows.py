# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The "Hold deal" match rows of a request: kept in step with the deals that hold it (design 5.2)."""

import frappe
from frappe import _

from crm.privacy import notify

DEAL = "CRM Deal"
HOLD, REMOVED = "Hold deal", "Removed from open deal"


def sync_rows(doc, facts, held: dict) -> bool:
	"""Make the "Hold deal" rows say what the records say now. A confirmed or starting row keeps its relation; only a
	pure suggestion is relabelled. A "Hold deal" row that stops holding becomes: gone (deal deleted), Direct (confirmed
	meanwhile), Linked (closed with her still on it: a suggestion to confirm, [I2]) or "Removed from open deal"."""
	rows = {(r.reference_doctype, r.reference_name): r for r in doc.matches}
	changed = False
	for deal, why in held.items():
		row = rows.get((DEAL, deal))
		if row is None:
			doc.append(
				"matches",
				{
					"reference_doctype": DEAL,
					"reference_name": deal,
					"label": (frappe.db.get_value(DEAL, deal, "organization") or deal)[:140],
					"reason": _("Open deal that lists the person")
					if why == notify.CONTACT_HOLD
					else _("Open deal included in the request"),
					"confirmed": 0,
					"relation": HOLD,
				},
			)
		elif not (row.confirmed or row.is_source) and row.relation != HOLD:
			row.relation = HOLD
		else:
			continue
		changed = True
	for row in list(doc.matches):
		if row.relation != HOLD or row.reference_name in held:
			continue
		changed = True
		deal = facts.state.get(row.reference_name)
		if deal is None:  # deleted
			doc.remove(row)
		elif row.confirmed:
			row.relation = "Direct"
		elif not deal.open and row.reference_name in facts.listing:
			row.relation = "Linked"
		else:
			row.relation = REMOVED
	return changed
