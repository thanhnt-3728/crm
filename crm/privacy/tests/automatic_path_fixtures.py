# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Fixtures for the paths that create leads without a person typing them in: WhatsApp and Facebook."""

from unittest.mock import patch

import frappe

from crm.lead_syncing.doctype.lead_sync_source.facebook import FacebookSyncSource
from crm.patches.v1_0.add_whatsapp_lead_source import execute as add_whatsapp_lead_source

FORM_ID = "privacy-test-form-1"


def incoming_whatsapp_message(number: str):
	"""An incoming WA Message from `number` on an account that turns new senders into leads."""
	add_whatsapp_lead_source()
	account = frappe.get_doc(
		{
			"doctype": "WA Account",
			"account_name": f"Privacy {frappe.generate_hash(length=5)}",
			"status": "Active",
			"phone_id": frappe.generate_hash(length=8),
			"append_actions": [
				{
					"append_to": "CRM Lead",
					"trigger_on": "Incoming",
					"sender_field": "mobile_no",
					"sender_name_field": "first_name",
				}
			],
		}
	).insert()
	profile = frappe.get_doc(
		{
			"doctype": "WA Profile",
			"whatsapp_account": account.name,
			"phone_number": number,
			"profile_name": "Marisol",
		}
	).insert()
	return frappe.get_doc(
		{
			"doctype": "WA Message",
			"direction": "Incoming",
			"whatsapp_account": account.name,
			"to": profile.name,
			"message": "Hi, tell me more",
		}
	)


def facebook_source() -> FacebookSyncSource:
	"""A sync source for a form that maps full_name and email, as the Lead Sync Source tests set one up."""
	frappe.get_doc(
		{
			"doctype": "Facebook Lead Form",
			"id": FORM_ID,
			"form_name": "Privacy test form",
			"questions": [
				{"key": "full_name", "mapped_to_crm_field": "first_name"},
				{"key": "email", "mapped_to_crm_field": "email"},
			],
		}
	).insert(ignore_links=True, ignore_mandatory=True)
	with patch(
		"crm.lead_syncing.doctype.lead_sync_source.lead_sync_source.fetch_and_store_pages_from_facebook"
	):
		source = frappe.get_doc(
			{
				"doctype": "Lead Sync Source",
				"__newname": "Privacy test source",
				"type": "Facebook",
				"access_token": "test-token",
				"facebook_lead_form": FORM_ID,
				"enabled": 0,
			}
		).insert(ignore_links=True, ignore_mandatory=True)
	return FacebookSyncSource("test-token", FORM_ID, source.name)


def meta_lead(lead_id: str, email: str) -> dict:
	return {
		"id": lead_id,
		"created_time": "2026-09-16T01:08:36+0500",
		"field_data": [
			{"name": "full_name", "values": ["Marisol Vega"]},
			{"name": "email", "values": [email]},
		],
	}
