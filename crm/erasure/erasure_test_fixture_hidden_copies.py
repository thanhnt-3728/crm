# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
"""Marisol fixture: WhatsApp, addresses, files and hidden copies (Version, queues, logs), with near misses"""

import json

import frappe

from crm.erasure.erasure_test_fixture_base import (
	COLLEAGUE_EMAIL,
	COLLEAGUE_PHONE,
	ERROR_LOG_METHOD,
	EXPECTED,
	HER_EMAILS,
	HER_IMAGE_URL,
	HIDDEN,
	NEAR_EMAIL,
	NEAR_MISSES,
	NEAR_PHONE,
	MarisolFixture,
	raw_insert,
)


def add_whatsapp(fx: MarisolFixture):
	account = raw_insert(
		{
			"doctype": "WA Account",
			"account_name": f"_Erasure {frappe.generate_hash(length=6)}",
			"status": "Active",
			"phone_id": frappe.generate_hash(length=8),
		}
	)
	on_account = {"whatsapp_account": account.name}
	hers = fx.seed(EXPECTED, "wa_profile_her", "WA Profile", **on_account, phone_number="+14155550123")
	kai = fx.seed(NEAR_MISSES, "wa_profile_kai", "WA Profile", **on_account, phone_number=COLLEAGUE_PHONE)
	incoming = {**on_account, "direction": "Incoming", "message": "Hola"}
	fx.seed(EXPECTED, "wa_to_her_profile", "WA Message", **incoming, to=hers)
	fx.seed(EXPECTED, "wa_from_her_number", "WA Message", **incoming, to=kai, **{"from": "+1 (415) 555-0177"})
	fx.seed(NEAR_MISSES, "wa_colleague", "WA Message", **incoming, to=kai, **{"from": COLLEAGUE_PHONE})


def add_addresses_and_files(fx: MarisolFixture):
	street = {
		"address_type": "Billing",
		"address_line1": "1 Main St",
		"city": "Oakland",
		"country": "United States",
	}
	her_link = {"link_doctype": "Contact", "link_name": fx.contact}
	kai_link = {"link_doctype": "Contact", "link_name": fx.colleague_contact}
	fx.seed(EXPECTED, "address_hers", "Address", **street, links=[her_link])
	fx.seed(EXPECTED, "address_shared", "Address", **street, links=[her_link, kai_link])

	def file(bucket, label, **values):
		values = {
			"file_name": f"{label}.txt",
			"file_url": f"/private/files/{label}.txt",
			"is_private": 1,
			**values,
		}
		fx.seed(bucket, label, "File", **values)

	file(EXPECTED, "file_on_lead", attached_to_doctype="CRM Lead", attached_to_name=fx.lead)
	comm = fx.names["comm_on_lead"]
	file(EXPECTED, "file_on_email", attached_to_doctype="Communication", attached_to_name=comm)
	on_her_contact = {"attached_to_doctype": "Contact", "attached_to_name": fx.contact}
	file(EXPECTED, "file_contact_image", file_url=HER_IMAGE_URL, attached_to_field="image", **on_her_contact)
	# Frappe dedups uploads by content: a colleague's File row may share her file_url
	on_kai = {"attached_to_doctype": "Contact", "attached_to_name": fx.colleague_contact}
	file(NEAR_MISSES, "file_shared_with_colleague", file_url=HER_IMAGE_URL, **on_kai)
	on_colleague_deal = {"attached_to_doctype": "CRM Deal", "attached_to_name": fx.colleague_deal}
	file(NEAR_MISSES, "file_on_colleague_deal", **on_colleague_deal)


def add_hidden_copies(fx: MarisolFixture):
	_add_versions(fx)
	deleted = {"deleted_doctype": "FCRM Note"}
	data = json.dumps({"content": "Call her on +14155550123"})
	fx.seed(HIDDEN, "deleted_note", "Deleted Document", **deleted, deleted_name="n-old", data=data)
	data = json.dumps({"content": f"Call {NEAR_PHONE}"})
	fx.seed(NEAR_MISSES, "deleted_other", "Deleted Document", **deleted, deleted_name="n-other", data=data)

	sent = {"status": "Sent", "message": "x"}
	to_her = [{"recipient": HER_EMAILS[1].lower(), "status": "Sent"}]
	fx.seed(HIDDEN, "queue_to_her", "Email Queue", **sent, recipients=to_her)
	to_rep = [{"recipient": "erq.rep@example.com", "status": "Sent"}]
	comm = fx.names["comm_on_lead"]
	fx.seed(HIDDEN, "queue_for_comm", "Email Queue", **sent, communication=comm, recipients=to_rep)
	to_kai = [{"recipient": COLLEAGUE_EMAIL, "status": "Sent"}]
	fx.seed(NEAR_MISSES, "queue_colleague", "Email Queue", **sent, recipients=to_kai)

	webhook = {"message": "webhook", "event_type": "Webhook"}
	data = json.dumps({"contacts": [{"wa_id": "14155550123"}]})
	fx.seed(HIDDEN, "wa_log_her", "WA Log", **webhook, request_data=data)
	data = json.dumps({"contacts": [{"wa_id": "14155550124"}]})
	fx.seed(NEAR_MISSES, "wa_log_other", "WA Log", **webhook, request_data=data)

	# tabError Log is MyISAM: rollback leaves these rows, `cleanup_marisol` deletes them by method
	logged = {"method": ERROR_LOG_METHOD}
	fx.seed(HIDDEN, "error_log_her", "Error Log", **logged, error=f"SMTP rejected {HER_EMAILS[0]}")
	fx.seed(NEAR_MISSES, "error_log_other", "Error Log", **logged, error=f"SMTP rejected {NEAR_EMAIL}")


def _add_versions(fx: MarisolFixture):
	def version(bucket, label, ref_doctype, docname, data):
		fx.seed(bucket, label, "Version", ref_doctype=ref_doctype, docname=docname, data=json.dumps(data))

	version(HIDDEN, "version_on_lead", "CRM Lead", fx.lead, {"changed": [["status", "New", "Contacted"]]})
	version(HIDDEN, "version_on_note", "FCRM Note", fx.names["note_on_deal"], {})
	row_changed = {"row_changed": [["contacts", 2, "x", [["email", None, HER_EMAILS[0]]]]]}
	version(HIDDEN, "version_mentions_her", "CRM Deal", fx.colleague_deal, row_changed)
	near = {"changed": [["email", None, NEAR_EMAIL]]}
	version(NEAR_MISSES, "version_colleague", "CRM Deal", fx.colleague_deal, near)
