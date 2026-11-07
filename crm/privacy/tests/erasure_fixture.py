# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The Marisol Vega scenario of design 5.6, built for the phase 05 tests (preview, approval, executor).

`ErasureTestCase.setUp` builds everything and leaves one request `Awaiting sign-off`, logged by a Sales Manager,
with her lead and contact and the Won deal confirmed, the Negotiation deal released (she was removed from it while
On Hold), and an excluded shared-inbox address. `self.p` holds every name. See `erasure_fixture_activity.py`.
"""

import os
from unittest.mock import patch

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field

from crm.api.erasure_requests import (
	recheck_hold,
	set_identifier_excluded,
	set_match_confirmed,
	submit_request,
	suggest_matches,
)
from crm.api.whatsapp import CONFIRM_PARAM
from crm.privacy.tests.erasure_fixture_activity import add_activity
from crm.privacy.tests.erasure_fixture_files import BYTES
from crm.privacy.tests.make_test_user import (
	RequestTestCase,
	as_user,
	make_contact,
	make_deal,
	make_lead,
	make_request,
	match_rows,
)

EMAIL, EMAIL2 = "m.vega@example.com", "marisol.vega@gmail.example"
PHONE, PHONE2 = "+15305550101", "+15305550103"
PERSONAL_MOBILE = "+15305550104"  # in a custom field that is not on the personal-fields list
SHARED, COLLEAGUE = "office@sierra.example.com", "jon.park@sierra.example.com"
LOOKALIKE_EMAIL, LOOKALIKE_PHONE = "adam.vega@example.com", "+153055501019"  # contain hers as a part
CUSTOM_FIELD = "CRM Lead-personal_mobile"


def ensure_personal_mobile() -> None:
	"""The custom field of the scenario. Adding a column is DDL, which commits: do it once per test class."""
	if not frappe.db.exists("Custom Field", CUSTOM_FIELD):
		create_custom_field(
			"CRM Lead", {"fieldname": "personal_mobile", "label": "Personal mobile", "fieldtype": "Data"}
		)
	frappe.db.commit()


def drop_personal_mobile() -> None:
	if frappe.db.exists("Custom Field", CUSTOM_FIELD):
		frappe.delete_doc("Custom Field", CUSTOM_FIELD, force=True)
	frappe.db.commit()


def build_records(rep: str) -> frappe._dict:
	"""Her lead, contact, address and deals, the colleague she shares an inbox with, and a stranger whose
	email and phone contain hers as a part. `rep` owns the Negotiation deal."""
	p = frappe._dict(
		rep=rep,
		rep_email=rep,
		email=EMAIL,
		email2=EMAIL2,
		phone=PHONE,
		phone2=PHONE2,
		shared_email=SHARED,
		colleague_email=COLLEAGUE,
		lookalike_phone=LOOKALIKE_PHONE,
	)
	p.lead = make_lead(
		owner=rep, email=EMAIL, mobile_no=PHONE, job_title="Practice manager", personal_mobile=PERSONAL_MOBILE
	)
	p.lookalike = make_lead(first_name="Adam", email=LOOKALIKE_EMAIL, mobile_no=LOOKALIKE_PHONE)
	p.contact = make_contact("Marisol", emails=[EMAIL, EMAIL2], phones=[PHONE, PHONE2])
	frappe.db.set_value("Contact", p.contact, "designation", "Practice manager")
	p.colleague = make_contact("Jon", emails=[COLLEAGUE, SHARED], phones=["+15305550177"], last_name="Park")
	address = frappe.get_doc(
		{
			"doctype": "Address",
			"address_title": "Marisol Vega",
			"address_type": "Billing",
			"address_line1": "1 Foothill Road",
			"city": "Chico",
			"country": "United States",
			"email_id": EMAIL,
			"phone": PHONE,
			"links": [{"link_doctype": "Contact", "link_name": p.contact}],
		}
	).insert(ignore_permissions=True)
	p.address = address.name
	p.won = make_deal([p.contact, p.colleague], status="Won", lead=p.lead, deal_value=12000)
	p.copy_deal = make_deal(
		[p.colleague, p.contact], status="Won", deal_value=3000
	)  # RT-14: hers, never confirmed
	p.removed = make_deal([p.contact, p.colleague], owner=rep, status="Negotiation", deal_value=8000)
	return p


def release_removed_deal(p) -> None:
	"""She was taken off the Negotiation deal while the request was On Hold."""
	deal = frappe.get_doc("CRM Deal", p.removed)
	deal.contacts = [row for row in deal.contacts if row.contact != p.contact]
	deal.contacts[0].is_primary = 1
	frappe.form_dict[CONFIRM_PARAM] = 1  # the rep confirmed the WhatsApp "change recipient?" question
	try:
		deal.save(ignore_permissions=True)
	finally:
		frappe.form_dict.pop(CONFIRM_PARAM, None)


def row_name(request: str, doctype: str, record: str) -> str:
	return match_rows(request)[(doctype, record)].name


def log_request(case, p) -> str:
	"""Logged from her lead by the Sales Manager, matched, confirmed, submitted (On Hold: she is on the open deal),
	released, and rechecked by Compliance: Awaiting sign-off."""
	name = make_request(
		case.manager,
		source_doctype="CRM Lead",
		source_name=p.lead,
		emails=[p.shared_email],
		requester_names="Marisol Vega",
	)
	as_user(case.manager, suggest_matches, name)
	for doctype, record in (("Contact", p.contact), ("CRM Deal", p.won)):
		as_user(case.manager, set_match_confirmed, name, row_name(name, doctype, record), True)
	shared = next(
		i for i in frappe.get_doc("CRM Erasure Request", name).identifiers if i.value == p.shared_email
	)
	as_user(case.manager, set_identifier_excluded, name, shared.name, True)
	assert as_user(case.manager, submit_request, name)["status"] == "On Hold"
	release_removed_deal(p)
	assert as_user(case.compliance, recheck_hold, name)["status"] == "Awaiting sign-off"
	return name


def remove_bytes() -> None:
	for path in BYTES:
		if os.path.exists(path):
			os.remove(path)
	BYTES.clear()


class ErasureTestCase(RequestTestCase):
	"""Builds the scenario in `setUp`; `self.p` has the records, `self.request` the request, `self.activity`
	the rows around them. The bytes of the fixture's files (`self.paths`) are removed afterwards: a rollback leaves them."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_personal_mobile()

	@classmethod
	def tearDownClass(cls):
		drop_personal_mobile()
		super().tearDownClass()

	def setUp(self):
		# No worker runs in the test bench: a real enqueue (comments, notifications) would pile up in Redis until the
		# queue refuses more (QueueOverloaded). Tests that look at an enqueue patch it again themselves.
		enqueue = patch("frappe.enqueue")
		enqueue.start()
		self.addCleanup(enqueue.stop)
		self.addCleanup(remove_bytes)
		self.addCleanup(
			frappe.db.rollback
		)  # a failed setUp skips tearDown, and the next test must start clean
		super().setUp()
		self.p = build_records(self.other)
		self.activity = add_activity(self.p)
		self.request = log_request(self, self.p)
		self.paths = list(BYTES)
