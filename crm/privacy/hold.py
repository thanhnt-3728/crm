"""Holding an erasure request while the person is still on an open deal.

A request waits On Hold while a confirmed Contact match is linked to a deal whose status
type is Open, Ongoing or On Hold. Removing the contact or closing the deal releases it.
Status changes here go through `frappe.db.set_value`: they are system changes made after
the caller's own checks, and `modified` is updated so the change shows in the request.
"""

import frappe

from crm.privacy.reminders import notify

DOCTYPE = "CRM Erasure Request"
OPEN_STATUS_TYPES = ("Open", "Ongoing", "On Hold")


def _open_deal_contacts(request) -> list[tuple[str, str]]:
	"""(deal, contact) pairs for the request's confirmed Contact matches on open deals."""
	contacts = [m.reference_name for m in request.matches if m.reference_doctype == "Contact" and m.confirmed]
	if not contacts:
		return []

	links = frappe.get_all(
		"CRM Contacts",
		filters={"parenttype": "CRM Deal", "contact": ["in", contacts]},
		fields=["parent", "contact"],
		order_by="parent asc, idx asc",
		parent_doctype="CRM Deal",
		ignore_permissions=True,
	)
	if not links:
		return []

	deals = {
		d.name: d.status
		for d in frappe.get_all(
			"CRM Deal",
			filters={"name": ["in", list({link.parent for link in links})]},
			fields=["name", "status"],
			ignore_permissions=True,
		)
	}
	open_statuses = set(
		frappe.get_all(
			"CRM Deal Status",
			filters={"type": ["in", OPEN_STATUS_TYPES]},
			pluck="name",
			ignore_permissions=True,
		)
	)
	return [(link.parent, link.contact) for link in links if deals.get(link.parent) in open_statuses]


def open_deals_for(request) -> list[str]:
	"""Open deals the request's confirmed Contact matches are linked to."""
	return sorted({deal for deal, _contact in _open_deal_contacts(request)})


def apply_hold(request) -> bool:
	"""Put the request On Hold and tell the deal owners, when it has open deals."""
	pairs = _open_deal_contacts(request)
	if not pairs:
		return False

	frappe.db.set_value(DOCTYPE, request.name, "status", "On Hold")
	request.status = "On Hold"

	owners = dict(
		frappe.get_all(
			"CRM Deal",
			filters={"name": ["in", list({deal for deal, _contact in pairs})]},
			fields=["name", "deal_owner"],
			as_list=True,
			ignore_permissions=True,
		)
	)
	for deal, contact in dict.fromkeys(pairs):
		owner = owners.get(deal)
		if not owner:
			continue
		contact_name = frappe.db.get_value("Contact", contact, "full_name") or contact
		notify(
			[owner],
			f"Erasure request {request.name} is on hold: contact {contact_name} on deal {deal} "
			"asked to be erased. Remove them from the deal or close it.",
			request.name,
			reference_doctype="CRM Deal",
			reference_name=deal,
		)
	return True


def on_deal_update(doc, method=None) -> None:
	"""Release On Hold requests whose contacts are no longer on any open deal."""
	for name in frappe.get_all(DOCTYPE, filters={"status": "On Hold"}, pluck="name", ignore_permissions=True):
		request = frappe.get_doc(DOCTYPE, name)
		if not open_deals_for(request):
			frappe.db.set_value(DOCTYPE, name, "status", "Awaiting Sign-off")
