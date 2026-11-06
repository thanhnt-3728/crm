# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
"""Marisol fixture, people: her lead, contact and two deals; a colleague's deal; namesakes and near misses

Inserted for real, as their owner: a Sales User reads only what they own (phase 01 fixtures).
"""

import frappe

from crm.erasure.erasure_test_fixture_base import (
	COLLEAGUE_EMAIL,
	COLLEAGUE_PHONE,
	EXPECTED,
	HER_EMAILS,
	HER_IMAGE_URL,
	HER_PHONE_DATA,
	NEAR_EMAIL,
	NEAR_MISSES,
	NEAR_PHONE,
	OPEN_STATUS,
	WON_STATUS,
	MarisolFixture,
	insert_as,
)
from crm.fcrm.doctype.crm_erasure_request.erasure_test_fixtures import (
	REP,
	REP2,
	as_user,
	ensure_deal_status,
	set_deal_status,
)


def add_people(fx: MarisolFixture):
	ensure_deal_status(OPEN_STATUS, "Ongoing")
	ensure_deal_status(WON_STATUS, "Won")
	contact = _contact("Marisol", "Reyes", HER_EMAILS, HER_PHONE_DATA)
	fx.contact = fx.add(EXPECTED, "contact", contact)
	# set raw: an image on insert makes Frappe attach it and log "Error Attaching File" (non-transactional)
	frappe.db.set_value("Contact", contact.name, "image", HER_IMAGE_URL, update_modified=False)
	lead = insert_as(
		REP,
		{
			"doctype": "CRM Lead",
			"first_name": "Marisol",
			"last_name": "Reyes",
			"lead_owner": REP,
			"email": HER_EMAILS[0],
			"mobile_no": HER_PHONE_DATA[0],
		},
	)
	fx.lead = fx.add(EXPECTED, "lead", lead)
	lead_values = {"converted": 1, "image": "/files/marisol-lead.png"}
	frappe.db.set_value("CRM Lead", lead.name, lead_values, update_modified=False)

	colleague = _contact("Kai", "Colleague", (COLLEAGUE_EMAIL,), (COLLEAGUE_PHONE,))
	fx.colleague_contact = fx.add(NEAR_MISSES, "colleague_contact", colleague)

	for label, status in (("deal_won", WON_STATUS), ("deal_open", OPEN_STATUS)):
		deal = _deal(REP, lead=lead.name, contact=contact.name, contacts=[{"contact": contact.name}])
		if status != OPEN_STATUS:
			with as_user(REP):
				set_deal_status(deal.name, status)
		setattr(fx, label, fx.add(EXPECTED, label, deal))
		fx.expected["CRM Contacts"].update(str(row.name) for row in deal.contacts)

	# A colleague's deal where she is only a secondary contact: the deal is not hers, her row is
	rows = [{"contact": colleague.name, "is_primary": 1}, {"contact": contact.name}]
	deal = _deal(REP2, contact=colleague.name, contacts=rows)
	fx.colleague_deal = fx.add(NEAR_MISSES, "colleague_deal", deal)
	for row in deal.contacts:
		hers = row.contact == contact.name
		getattr(fx, EXPECTED if hers else NEAR_MISSES)["CRM Contacts"].add(str(row.name))
		fx.names[f"colleague_deal_row_{'her' if hers else 'kai'}"] = str(row.name)


def add_near_miss_people(fx: MarisolFixture):
	"""Same name, different person; an email that contains hers; a phone one digit off"""
	for label, values in (
		("namesake_lead", {"first_name": "Marisol", "last_name": "Reyes", "email": "marisol.r@example.org"}),
		("near_email_lead", {"first_name": "Jo", "email": NEAR_EMAIL}),
		("near_phone_lead", {"first_name": "Pat", "mobile_no": NEAR_PHONE}),
	):
		lead = insert_as(REP2, {"doctype": "CRM Lead", "lead_owner": REP2, **values})
		fx.add(NEAR_MISSES, label, lead)
	fx.add(NEAR_MISSES, "near_contact", _contact("Marisol", "Reyes", (NEAR_EMAIL,), (NEAR_PHONE,)))


def _contact(first_name: str, last_name: str, emails: tuple, phones: tuple):
	email_ids = [{"email_id": email, "is_primary": int(i == 0)} for i, email in enumerate(emails)]
	phone_nos = [
		{"phone": phone, "is_primary_mobile_no": int(i == 0), "is_primary_phone": int(i == 1)}
		for i, phone in enumerate(phones)
	]
	values = {
		"first_name": first_name,
		"last_name": last_name,
		"email_ids": email_ids,
		"phone_nos": phone_nos,
	}
	return insert_as("Administrator", {"doctype": "Contact", **values})


def _deal(owner: str, **values):
	values = {"doctype": "CRM Deal", "deal_owner": owner, "status": OPEN_STATUS, "deal_value": 5000, **values}
	return insert_as(owner, values)
