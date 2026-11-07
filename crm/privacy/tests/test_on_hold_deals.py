# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Which open deals hold a request (design 5.2, RT-2, RT-14)."""

import frappe

from crm.api.erasure_requests import recheck_hold, set_match_confirmed, submit_request, suggest_matches
from crm.privacy.on_hold import is_open_deal
from crm.privacy.tests.make_test_user import (
	add_match,
	as_user,
	make_contact,
	make_deal,
	make_request,
	match_rows,
)
from crm.privacy.tests.test_on_hold import CONTACT, DEAL, LEAD, OnHoldCase, notices


class TestWhichDealsHold(OnHoldCase):
	def test_a_deal_that_only_matches_does_not_hold_until_it_is_confirmed(self):
		converted = make_deal([], status="Negotiation", lead=self.person.lead, owner=self.other)
		name = make_request(self.manager, source_doctype=LEAD, source_name=self.person.lead)
		as_user(self.manager, suggest_matches, name)
		self.assertEqual(match_rows(name)[(DEAL, converted)].relation, "Linked")
		self.assertEqual(match_rows(name)[(DEAL, self.person.negotiation)].confirmed, 0)
		self.assertEqual(as_user(self.manager, submit_request, name)["status"], "Awaiting sign-off")

	def test_a_confirmed_open_deal_converted_from_her_lead_holds_it(self):
		converted = make_deal([], status="Negotiation", lead=self.person.lead, owner=self.other)
		name = make_request(self.manager, source_doctype=LEAD, source_name=self.person.lead)
		as_user(self.manager, suggest_matches, name)
		row = match_rows(name)[(DEAL, converted)]
		as_user(self.manager, set_match_confirmed, name, row.name, True)
		self.assertEqual(as_user(self.manager, submit_request, name)["status"], "On Hold")
		held = match_rows(name)[(DEAL, converted)]
		self.assertEqual((held.relation, held.confirmed), ("Linked", 1))  # a confirmed row keeps its relation
		(note,) = notices(self.other, reference_name=converted)
		self.assertIn("unconfirm", note.message.lower())

	def test_the_notice_for_the_starting_deal_only_says_to_close_it(self):
		solo = make_deal([], status="Negotiation", owner=self.other)
		name = make_request(self.manager, source_doctype=DEAL, source_name=solo)
		self.assertEqual(as_user(self.manager, submit_request, name)["status"], "On Hold")
		(note,) = notices(self.other, reference_name=solo)
		self.assertIn("close", note.message.lower())
		self.assertNotIn("unconfirm", note.message.lower())
		self.assertEqual(match_rows(name)[(DEAL, solo)].relation, "Direct")  # the starting row is left alone

	def test_unconfirming_the_held_deal_releases_the_request(self):
		converted = make_deal([], status="Negotiation", lead=self.person.lead, owner=self.other)
		name = make_request(self.manager, source_doctype=LEAD, source_name=self.person.lead)
		add_match(name, DEAL, converted, confirmed=1, relation="Linked")
		as_user(self.manager, submit_request, name)
		self.assertEqual(frappe.db.get_value("CRM Erasure Request", name, "status"), "On Hold")
		row = match_rows(name)[(DEAL, converted)]
		result = as_user(self.compliance, set_match_confirmed, name, row.name, False)
		self.assertEqual(result["status"], "Awaiting sign-off")
		self.assertEqual(
			match_rows(name)[(DEAL, converted)].relation, "Linked"
		)  # never relabelled, still a suggestion

	def test_confirming_a_new_open_deal_on_a_held_request_keeps_it_held(self):
		self.submit()
		other = make_deal([], status="Qualification", owner=self.other)
		add_match(self.name, DEAL, other, confirmed=0, relation="Direct")
		row = match_rows(self.name)[(DEAL, other)]
		result = as_user(self.compliance, set_match_confirmed, self.name, row.name, True)
		self.assertEqual(result["status"], "On Hold")
		self.assertEqual(match_rows(self.name)[(DEAL, other)].relation, "Direct")  # confirmed: relation kept
		self.assertEqual(len(notices(self.other, reference_name=other)), 1)

	def test_an_unconfirmed_suggestion_that_starts_holding_becomes_a_hold_deal_row(self):
		self.submit()
		other = make_deal([self.person.contact], status="Qualification", owner=self.other)
		add_match(self.name, DEAL, other, confirmed=0, relation="Linked")
		as_user(self.compliance, recheck_hold, self.name)
		held = match_rows(self.name)[(DEAL, other)]
		self.assertEqual((held.relation, held.confirmed), ("Hold deal", 0))

	def test_confirming_an_open_deal_on_a_signed_off_request_puts_it_on_hold(self):
		frappe.db.set_value(DEAL, self.person.negotiation, "status", "Won")
		self.submit()
		self.assertEqual(self.stored().status, "Awaiting sign-off")
		other = make_deal([], status="Qualification", owner=self.other)
		add_match(self.name, DEAL, other, confirmed=0, relation="Direct")
		row = match_rows(self.name)[(DEAL, other)]
		result = as_user(self.compliance, set_match_confirmed, self.name, row.name, True)
		self.assertEqual(result["status"], "On Hold")
		self.assertEqual(len(notices(self.other, reference_name=other)), 1)
		released = as_user(self.compliance, set_match_confirmed, self.name, row.name, False)
		self.assertEqual(released["status"], "Awaiting sign-off")

	def test_recheck_moves_a_signed_off_request_back_on_hold_when_a_deal_opens(self):
		frappe.db.set_value(DEAL, self.person.negotiation, "status", "Won")
		self.submit()
		self.assertEqual(self.stored().status, "Awaiting sign-off")
		frappe.db.set_value(DEAL, self.person.negotiation, "status", "Negotiation")
		result = as_user(self.compliance, recheck_hold, self.name)
		self.assertEqual(result["status"], "On Hold")
		self.assertEqual(len(notices(self.other, reference_name=self.person.negotiation)), 1)
		again = as_user(self.compliance, recheck_hold, self.name)
		self.assertEqual(again["status"], "On Hold")
		self.assertEqual(len(notices(self.other, reference_name=self.person.negotiation)), 1)

	def test_a_contact_with_no_deals_goes_straight_to_sign_off(self):
		solo = make_contact("Solo", emails=["solo@example.com"], last_name="Person")
		name = make_request(self.manager, source_doctype=CONTACT, source_name=solo)
		self.assertEqual(as_user(self.manager, submit_request, name)["status"], "Awaiting sign-off")


class TestOpenDeal(OnHoldCase):
	def test_open_ongoing_and_on_hold_types_are_open(self):
		frappe.get_doc(
			{"doctype": "CRM Deal Status", "deal_status": "Paused Test", "type": "On Hold"}
		).insert(ignore_permissions=True)
		for status, expected in (
			("Qualification", True),
			("Negotiation", True),
			("Paused Test", True),
			("Won", False),
		):
			deal = make_deal([], status=status)
			with self.subTest(status=status):
				self.assertEqual(is_open_deal(deal), expected)

	def test_a_missing_deal_is_not_open(self):
		self.assertFalse(is_open_deal("CRM-DEAL-NO-SUCH"))
