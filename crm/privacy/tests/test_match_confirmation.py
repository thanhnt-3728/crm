# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Confirming matches: the identifiers they pull in, linked suggestions, the starting record, deleted records."""

import frappe

from crm.api.erasure_requests import get_request, set_match_confirmed, suggest_matches
from crm.privacy.tests.make_test_user import (
	RequestTestCase,
	add_match,
	as_user,
	make_contact,
	make_deal,
	make_lead,
	make_person,
	make_request,
	match_rows,
)

LEAD, DEAL, CONTACT = "CRM Lead", "CRM Deal", "Contact"


class TestConfirmation(RequestTestCase):
	def setUp(self):
		super().setUp()
		self.person = make_person()

	def identifiers(self, name):
		return [
			(i.kind, i.value, i.source, i.source_doctype, i.source_name)
			for i in frappe.get_doc("CRM Erasure Request", name).identifiers
		]

	def suggested(self, **values):
		name = make_request(self.manager, **{"emails": ["m.vega@example.com"], **values})
		as_user(self.manager, suggest_matches, name)
		return name

	def test_confirming_a_lead_pulls_its_email_and_phones_as_record_identifiers(self):
		lead = make_lead(
			first_name="Pull", email="pull@example.com", mobile_no="+15305550142", phone="+15305550143"
		)
		name = self.suggested(emails=["pull@example.com"])
		row = match_rows(name)[(LEAD, lead)]
		result = as_user(self.manager, set_match_confirmed, name, row.name, True)
		self.assertEqual(result["skipped_identifiers"], [])
		found = self.identifiers(name)
		self.assertIn(("Phone", "+15305550142", "Record", LEAD, lead), found)
		self.assertIn(("Phone", "+15305550143", "Record", LEAD, lead), found)
		typed = [i for i in found if i[1] == "pull@example.com"]
		self.assertEqual([i[2] for i in typed], ["Typed"])

	def test_invalid_stored_values_are_skipped_and_listed(self):
		lead = make_lead(first_name="Bad", email="bad@example.com", mobile_no="12")
		name = self.suggested(emails=["bad@example.com"])
		row = match_rows(name)[(LEAD, lead)]
		result = as_user(self.manager, set_match_confirmed, name, row.name, True)
		self.assertEqual(len(result["skipped_identifiers"]), 1)
		skipped = result["skipped_identifiers"][0]
		self.assertEqual((skipped["doctype"], skipped["name"], skipped["value"]), (LEAD, lead, "12"))
		self.assertNotIn("12", [i[1] for i in self.identifiers(name)])

	def test_confirming_a_contact_pulls_every_email_and_phone(self):
		contact = make_contact(
			"Multi",
			emails=["a1@example.com", "a2@example.com"],
			phones=["+15305550151", "+15305550152"],
			last_name="Person",
		)
		name = self.suggested(emails=["a1@example.com"])
		row = match_rows(name)[(CONTACT, contact)]
		as_user(self.manager, set_match_confirmed, name, row.name, True)
		values = {i[1] for i in self.identifiers(name)}
		self.assertTrue({"a1@example.com", "a2@example.com", "+15305550151", "+15305550152"} <= values)

	def test_confirming_re_runs_the_linked_suggestions(self):
		converted = make_deal([], status="Negotiation", lead=self.person.lead)
		name = self.suggested(emails=["m.vega@example.com"])
		row = match_rows(name)[(LEAD, self.person.lead)]
		as_user(self.manager, set_match_confirmed, name, row.name, True)
		self.assertEqual(match_rows(name)[(DEAL, converted)].relation, "Linked")
		self.assertEqual(match_rows(name)[(DEAL, converted)].confirmed, 0)

	def test_unconfirming_flips_the_flag_and_keeps_the_identifiers(self):
		name = self.suggested()
		row = match_rows(name)[(LEAD, self.person.lead)]
		as_user(self.manager, set_match_confirmed, name, row.name, True)
		before = self.identifiers(name)
		as_user(self.manager, set_match_confirmed, name, row.name, False)
		self.assertEqual(match_rows(name)[(LEAD, self.person.lead)].confirmed, 0)
		self.assertEqual(self.identifiers(name), before)

	def test_the_starting_record_cannot_be_unconfirmed(self):
		name = make_request(self.manager, source_doctype=LEAD, source_name=self.person.lead)
		row = match_rows(name)[(LEAD, self.person.lead)]
		with self.assertRaises(frappe.ValidationError):
			as_user(self.manager, set_match_confirmed, name, row.name, False)
		self.assertEqual(match_rows(name)[(LEAD, self.person.lead)].confirmed, 1)

	def test_an_unknown_row_is_refused(self):
		name = self.suggested()
		with self.assertRaises(frappe.ValidationError):
			as_user(self.manager, set_match_confirmed, name, "no-such-row", True)

	def test_a_deleted_record_cannot_be_confirmed(self):
		gone = make_lead(first_name="Gone", email="gone@example.com")
		name = make_request(self.manager, emails=["m.vega@example.com"])
		add_match(name, LEAD, gone, confirmed=0)
		frappe.delete_doc(LEAD, gone, force=True)
		row = match_rows(name)[(LEAD, gone)]
		with self.assertRaises(frappe.ValidationError):
			as_user(self.compliance, set_match_confirmed, name, row.name, True)

	def test_compliance_can_unconfirm_a_row_whose_record_was_deleted(self):
		gone = make_lead(first_name="Gone", email="gone@example.com")
		name = make_request(self.manager)
		add_match(name, LEAD, gone, confirmed=1)
		frappe.delete_doc(LEAD, gone, force=True)
		row = match_rows(name)[(LEAD, gone)]
		as_user(self.compliance, set_match_confirmed, name, row.name, False)
		self.assertEqual(match_rows(name)[(LEAD, gone)].confirmed, 0)

	def test_get_request_still_returns_a_row_whose_record_is_gone_to_compliance(self):
		gone = make_lead(first_name="Gone", email="gone@example.com")
		name = make_request(self.manager)
		add_match(name, LEAD, gone)
		frappe.delete_doc(LEAD, gone, force=True)
		shown = as_user(self.compliance, get_request, name)
		self.assertIn(gone, [m["reference_name"] for m in shown["matches"]])
