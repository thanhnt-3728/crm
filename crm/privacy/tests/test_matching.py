# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Suggested matches and confirmation (design 5.3)."""

import frappe

from crm.api.erasure_requests import (
	set_identifier_excluded,
	set_match_confirmed,
	suggest_matches,
)
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


def keys(request):
	return set(match_rows(request))


class TestSuggestions(RequestTestCase):
	def setUp(self):
		super().setUp()
		self.person = make_person()

	def request(self, **values):
		values.setdefault("emails", ["m.vega@example.com"])
		return make_request(self.manager, **values)

	def test_an_email_finds_every_record_that_holds_it(self):
		name = self.request()
		as_user(self.manager, suggest_matches, name)
		p = self.person
		self.assertEqual(
			keys(name), {(LEAD, p.lead), (CONTACT, p.contact), (DEAL, p.negotiation), (DEAL, p.won)}
		)

	def test_suggestions_are_unconfirmed_and_say_why(self):
		name = self.request()
		as_user(self.manager, suggest_matches, name)
		row = match_rows(name)[(LEAD, self.person.lead)]
		self.assertEqual((row.confirmed, row.is_source, row.relation), (0, 0, "Direct"))
		self.assertIn("m.vega@example.com", row.reason)
		self.assertIn("lead", row.reason.lower())
		self.assertTrue(row.label)

	def test_a_phone_typed_in_national_format_finds_the_stored_e164_number(self):
		other = make_lead(first_name="Punctuated", phone="530.555.0101")
		near = make_lead(first_name="Near", mobile_no="+15305550199")
		name = self.request(emails=None, phones=["(530) 555-0101"])
		as_user(self.manager, suggest_matches, name)
		found = keys(name)
		self.assertIn((LEAD, self.person.lead), found)
		self.assertIn((CONTACT, self.person.contact), found)
		self.assertIn((LEAD, other), found)
		self.assertNotIn((LEAD, near), found)

	def test_a_phone_stored_on_a_deal_contact_row_is_found(self):
		name = self.request(emails=None, phones=["+15305550101"])
		as_user(self.manager, suggest_matches, name)
		self.assertIn((DEAL, self.person.negotiation), keys(name))

	def test_running_it_twice_adds_nothing(self):
		name = self.request()
		as_user(self.manager, suggest_matches, name)
		first = len(frappe.get_doc("CRM Erasure Request", name).matches)
		as_user(self.manager, suggest_matches, name)
		self.assertEqual(len(frappe.get_doc("CRM Erasure Request", name).matches), first)

	def test_an_excluded_identifier_stops_matching(self):
		colleague = make_lead(first_name="Colleague", email="office@example.com")
		name = self.request(emails=["m.vega@example.com", "office@example.com"])
		as_user(self.manager, suggest_matches, name)
		self.assertIn((LEAD, colleague), keys(name))
		doc = frappe.get_doc("CRM Erasure Request", name)
		office = next(i.name for i in doc.identifiers if i.value == "office@example.com")
		as_user(self.manager, set_identifier_excluded, name, office, True)
		as_user(self.manager, suggest_matches, name)
		self.assertNotIn((LEAD, colleague), keys(name))

	def test_an_identifier_excluded_before_the_first_search_never_suggests(self):
		colleague = make_lead(first_name="Colleague", email="office@example.com")
		name = self.request(emails=["office@example.com", "m.vega@example.com"])
		doc = frappe.get_doc("CRM Erasure Request", name)
		office = next(i.name for i in doc.identifiers if i.value == "office@example.com")
		as_user(self.manager, set_identifier_excluded, name, office, True)
		as_user(self.manager, suggest_matches, name)
		self.assertNotIn((LEAD, colleague), keys(name))

	def test_a_confirmed_row_survives_when_its_identifier_is_excluded(self):
		colleague = make_lead(first_name="Colleague", email="office@example.com")
		name = self.request(emails=["office@example.com"])
		as_user(self.manager, suggest_matches, name)
		row = match_rows(name)[(LEAD, colleague)]
		as_user(self.manager, set_match_confirmed, name, row.name, True)
		identifier = frappe.get_doc("CRM Erasure Request", name).identifiers[0].name
		as_user(self.manager, set_identifier_excluded, name, identifier, True)
		as_user(self.manager, suggest_matches, name)
		self.assertEqual(match_rows(name)[(LEAD, colleague)].confirmed, 1)

	def test_wildcards_in_a_stored_identifier_do_not_widen_the_match(self):
		from crm.privacy.matching import find_by_email, find_by_phone

		wild = make_lead(first_name="Wild", email="m_vega@example.com")
		self.assertEqual(find_by_email("%@example.com"), [])
		self.assertEqual(find_by_email("m_vega@example.%"), [])
		self.assertEqual(find_by_phone("%%%%%%%%"), [])
		self.assertEqual([h["name"] for h in find_by_email("m_vega@example.com")], [wild])

	def test_an_email_field_on_the_personal_fields_list_is_searched_too(self):
		contact = make_contact("Stored", last_name="Only")
		frappe.db.set_value(CONTACT, contact, "email_id", "extra@example.com")
		from crm.privacy.matching import find_by_email

		(hit,) = find_by_email("extra@example.com")
		self.assertEqual((hit["doctype"], hit["name"]), (CONTACT, contact))
		self.assertIn("email_id", hit["reason"])

	def test_a_confirmed_lead_suggests_the_deal_converted_from_it(self):
		converted = make_deal([], status="Negotiation", lead=self.person.lead)
		name = self.request(emails=["unrelated@example.com"])
		add_match(name, LEAD, self.person.lead)
		as_user(self.manager, suggest_matches, name)
		row = match_rows(name)[(DEAL, converted)]
		self.assertEqual((row.confirmed, row.relation), (0, "Linked"))

	def test_a_confirmed_contact_suggests_the_deals_that_list_it(self):
		name = self.request(emails=["unrelated@example.com"])
		add_match(name, CONTACT, self.person.contact)
		as_user(self.manager, suggest_matches, name)
		rows = match_rows(name)
		for deal in (self.person.negotiation, self.person.won):
			self.assertEqual((rows[(DEAL, deal)].confirmed, rows[(DEAL, deal)].relation), (0, "Linked"))

	def test_a_row_for_a_deleted_record_does_not_break_matching(self):
		gone = make_lead(first_name="Gone", email="gone@example.com")
		name = self.request()
		add_match(name, LEAD, gone)
		frappe.delete_doc(LEAD, gone, force=True)
		as_user(self.compliance, suggest_matches, name)
		self.assertIn((LEAD, gone), keys(name))
		self.assertIn((LEAD, self.person.lead), keys(name))
