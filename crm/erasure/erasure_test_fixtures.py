# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
"""Marisol fixture: one person spread over every registry source, plus near misses (not a test module)

Reused by phases 03 and 05:
    fx = build_marisol()                # fx.expected / fx.hidden / fx.near_misses: {doctype: {names}}
    request = log_marisol_request(fx)   # Draft, server-normalized identifiers, no matches yet
    ...                                 # tearDown: frappe.db.rollback(); cleanup_marisol()
`fx.names[label]` gives single records (e.g. "comm_from_her", "address_shared"). Person records
are inserted for real as their owner; activity and hidden copies raw (no hooks), so counts are
exact. Only example.net addresses and 555 numbers.
"""

import frappe

from crm.erasure.erasure_test_fixture_activities import add_activities
from crm.erasure.erasure_test_fixture_base import (
	COLLEAGUE_EMAIL,
	COLLEAGUE_PHONE,
	ERROR_LOG_METHOD,
	HER_EMAILS,
	HER_IMAGE_URL,
	HER_PHONE_DATA,
	HER_PHONES,
	NEAR_EMAIL,
	NEAR_PHONE,
	MarisolFixture,
	insert_as,
	raw_insert,
)
from crm.erasure.erasure_test_fixture_hidden_copies import (
	add_addresses_and_files,
	add_hidden_copies,
	add_whatsapp,
)
from crm.erasure.erasure_test_fixture_people import add_near_miss_people, add_people
from crm.erasure.identifiers import identifier_rows
from crm.fcrm.doctype.crm_erasure_request.erasure_test_fixtures import REP, as_user, ensure_users

__all__ = [
	"COLLEAGUE_EMAIL",
	"COLLEAGUE_PHONE",
	"HER_EMAILS",
	"HER_IMAGE_URL",
	"HER_PHONES",
	"HER_PHONE_DATA",
	"NEAR_EMAIL",
	"NEAR_PHONE",
	"MarisolFixture",
	"build_marisol",
	"cleanup_marisol",
	"insert_as",
	"log_marisol_request",
	"raw_insert",
]


def build_marisol() -> MarisolFixture:
	"""Insert the whole scenario; callers roll back and call `cleanup_marisol` afterwards"""
	ensure_users()
	fx = MarisolFixture()
	add_people(fx)
	add_near_miss_people(fx)
	add_activities(fx)
	add_whatsapp(fx)
	add_addresses_and_files(fx)
	add_hidden_copies(fx)
	return fx


def cleanup_marisol():
	"""Delete what rollback cannot: fixture rows in non-transactional (MyISAM) tables"""
	frappe.db.delete("Error Log", {"method": ERROR_LOG_METHOD})


def log_marisol_request(
	fx: MarisolFixture,
	user: str = REP,
	source: tuple[str, str | None] = ("CRM Lead", None),
	emails: tuple[str, ...] = HER_EMAILS,
	phones: tuple[str, ...] = HER_PHONES,
):
	"""A Draft request with server-normalized identifiers, as `log_request` stores it (no matches)"""
	source_doctype, source_docname = source[0], source[1] or fx.lead
	rows = identifier_rows(emails, phones, region="US")
	with as_user(user):
		request = frappe.get_doc(
			{
				"doctype": "CRM Erasure Request",
				"subject_name": "Marisol Reyes",
				"source_doctype": source_doctype,
				"source_docname": source_docname,
				"received_on": frappe.utils.today(),
				"identifiers": [{"kind": row["kind"], "value": row["value"]} for row in rows],
			}
		).insert()
		request.set_identifiers(rows)
	return request
