# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from crm.fcrm.doctype.crm_erasure_request.erasure_hold import blocking_open_deals, refresh_hold
from crm.fcrm.doctype.crm_erasure_request.erasure_test_fixtures import (
	REP,
	as_user,
	ensure_deal_status,
	ensure_users,
	make_contact,
	make_deal,
	make_lead,
	make_request,
	set_deal_status,
)


class TestErasureHold(IntegrationTestCase):
	def setUp(self):
		ensure_users()
		self.contact = make_contact("Dana")
		self.other = make_contact("Someone")

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def submit(self, source_doctype, source_docname, matches=()):
		with as_user(REP):
			request = make_request(source_doctype, source_docname, matches)
			request.submit_for_approval()
		return request

	def status_of(self, request):
		return tuple(frappe.db.get_value("CRM Erasure Request", request.name, ["status", "hold_reason"]))

	def test_open_deal_holds_then_lost_releases(self):
		deal = make_deal(contacts=[{"contact": self.contact.name}])
		request = self.submit("Contact", self.contact.name)
		self.assertEqual(self.status_of(request), ("On Hold", deal.name))

		set_deal_status(deal.name, "Lost")
		self.assertEqual(self.status_of(request)[0], "Pending Approval")
		self.assertFalse(self.status_of(request)[1])

	def test_won_releases_and_reopening_holds_again(self):
		deal = make_deal(contact=self.contact.name)
		request = self.submit("Contact", self.contact.name)
		self.assertEqual(self.status_of(request)[0], "On Hold")
		set_deal_status(deal.name, "Won")
		self.assertEqual(self.status_of(request)[0], "Pending Approval")
		set_deal_status(deal.name, "Negotiation")
		self.assertEqual(self.status_of(request), ("On Hold", deal.name))

	def test_deal_without_her_does_not_hold(self):
		deal = make_deal(contacts=[{"contact": self.other.name}])
		request = self.submit("Contact", self.contact.name)
		self.assertEqual(self.status_of(request)[0], "Pending Approval")
		set_deal_status(deal.name, "Negotiation")
		self.assertEqual(self.status_of(request)[0], "Pending Approval")

	def test_deal_status_type_on_hold_still_counts_as_open(self):
		paused = ensure_deal_status("Erasure Test Paused", "On Hold")
		make_deal(contact=self.contact.name, status=paused)
		request = self.submit("Contact", self.contact.name)
		self.assertEqual(self.status_of(request)[0], "On Hold")

	def test_deal_via_her_lead_and_via_matches(self):
		lead = make_lead("Dana")
		lead_deal = make_deal(lead=lead.name)
		matched_deal = make_deal(contacts=[{"contact": self.other.name}])
		excluded_deal = make_deal(contacts=[{"contact": self.other.name}])
		matches = [
			("CRM Lead", lead.name),
			("CRM Deal", matched_deal.name),
			("CRM Deal", excluded_deal.name, 1),
		]
		request = self.submit("Contact", self.contact.name, matches)
		self.assertEqual(blocking_open_deals(request), sorted([lead_deal.name, matched_deal.name]))
		self.assertEqual(self.status_of(request)[0], "On Hold")
		self.assertNotIn(excluded_deal.name, self.status_of(request)[1])

	def test_source_deal_blocks_itself(self):
		deal = make_deal()
		request = self.submit("CRM Deal", deal.name)
		self.assertEqual(self.status_of(request), ("On Hold", deal.name))

	def test_new_deal_for_pending_request_puts_it_on_hold(self):
		request = self.submit("Contact", self.contact.name)
		self.assertEqual(self.status_of(request)[0], "Pending Approval")
		deal = make_deal(contacts=[{"contact": self.contact.name}])
		self.assertEqual(self.status_of(request), ("On Hold", deal.name))

	def test_deal_moved_off_her_contact_releases(self):
		deal = make_deal(contact=self.contact.name)
		request = self.submit("Contact", self.contact.name)
		self.assertEqual(self.status_of(request)[0], "On Hold")
		deal.reload()
		deal.contact = self.other.name
		deal.save(ignore_permissions=True)
		self.assertEqual(self.status_of(request)[0], "Pending Approval")

	def test_hold_reason_tracks_remaining_deals(self):
		first = make_deal(contact=self.contact.name)
		second = make_deal(contact=self.contact.name)
		request = self.submit("Contact", self.contact.name)
		self.assertEqual(self.status_of(request)[1], ", ".join(sorted([first.name, second.name])))
		set_deal_status(first.name, "Lost")
		self.assertEqual(self.status_of(request), ("On Hold", second.name))

	def test_refresh_hold_leaves_draft_alone(self):
		make_deal(contact=self.contact.name)
		with as_user(REP):
			draft = make_request("Contact", self.contact.name)
		refresh_hold(draft)
		self.assertEqual(self.status_of(draft)[0], "Draft")

	def test_deleting_a_holding_deal_releases_the_request(self):
		"""M4: the deal holds only via her contact, so the delete guard does not stop it"""
		deal = make_deal(contact=self.contact.name)
		request = self.submit("Contact", self.contact.name)
		self.assertEqual(self.status_of(request)[0], "On Hold")
		frappe.delete_doc("CRM Deal", deal.name)
		self.assertEqual(self.status_of(request)[0], "Pending Approval")

	def test_deal_hook_locks_the_request_row(self):
		"""M3: the hook reloads each request FOR UPDATE so concurrent deal saves serialize"""
		deal = make_deal(contact=self.other.name)
		request = self.submit("Contact", self.contact.name)
		calls = []
		real_get_doc = frappe.get_doc

		def spy(*args, **kwargs):
			if args[:1] == ("CRM Erasure Request",):
				calls.append(kwargs.get("for_update"))
			return real_get_doc(*args, **kwargs)

		with patch("crm.fcrm.doctype.crm_erasure_request.erasure_hold.frappe.get_doc", side_effect=spy):
			deal.reload()
			deal.contact = self.contact.name
			deal.save(ignore_permissions=True)
		self.assertTrue(calls)
		self.assertTrue(all(calls), calls)  # the hook's own load and the save's reload
		self.assertEqual(self.status_of(request)[0], "On Hold")
