# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
"""Forgery paths: what a caller can slip past the controller through saves and the table seams"""

import contextlib

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import today

from crm.fcrm.doctype.crm_erasure_request.erasure_test_fixtures import (
	PO,
	PO_REP,
	REP,
	REP2,
	approve,
	as_user,
	ensure_users,
	make_contact,
	make_deal,
	make_lead,
	make_request,
)


def db_value(request, field):
	return frappe.db.get_value("CRM Erasure Request", request.name, field)


class TestErasureRequestIntegrity(IntegrationTestCase):
	def setUp(self):
		ensure_users()
		self.contact = make_contact()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def log(self, user=REP, **fields):
		with as_user(user):
			return make_request("Contact", self.contact.name, **fields)

	def new_doc(self, **fields):
		return frappe.get_doc(
			{
				"doctype": "CRM Erasure Request",
				"subject_name": "Forged",
				"source_doctype": "Contact",
				"source_docname": self.contact.name,
				"received_on": today(),
				**fields,
			}
		)

	def test_transition_methods_refuse_unsaved_docs(self):
		"""H2: an unsaved doc must not be inserted straight into Approved"""
		with as_user(PO):
			doc = self.new_doc(status="Pending Approval")
			for call in (
				lambda: doc.transition_to("Approved", approver=PO),
				lambda: doc.save_system_fields(last_error="x"),
				lambda: doc.submit_for_approval(),
				lambda: doc.replace_matches([]),
			):
				# refused up front, not merely by the insert-time checks behind it
				with self.assertRaisesRegex(frappe.ValidationError, "as a Draft first"):
					call()
		self.assertFalse(frappe.db.exists("CRM Erasure Request", {"subject_name": "Forged"}))

	def test_internal_save_persists_only_its_own_fields(self):
		"""H3: submit_for_approval must not carry unsaved edits along"""
		request = self.log()
		with as_user(REP):
			request.approver = "Administrator"
			request.subject_name = "changed"
			with self.assertRaises(frappe.ValidationError):
				request.submit_for_approval()
		self.assertEqual(db_value(request, "status"), "Draft")
		self.assertEqual(db_value(request, "subject_name"), "Dana Test")
		self.assertFalse(db_value(request, "approver"))

	def test_matches_are_server_only_on_plain_saves(self):
		"""H4: neither insert nor a Draft save may write matches"""
		# matches sit at permlevel 1: a Sales User's rows are refused or reset, never stored
		forged = self.new_doc(matches=[{"ref_doctype": "User", "ref_name": "Administrator"}])
		request = self.log()
		request.append("matches", {"ref_doctype": "User", "ref_name": "Administrator"})
		for doc in (forged, request):
			with as_user(REP), contextlib.suppress(frappe.ValidationError):
				doc.save()
		for name in {forged.name, request.name} - {None}:
			self.assertEqual(frappe.db.count("CRM Erasure Match", {"parent": name}), 0)

	def test_match_seams(self):
		deal = make_deal()
		request = self.log()
		rows = [{"ref_doctype": "CRM Deal", "ref_name": deal.name, "reason": "linked", "action": "scrub"}]
		with as_user(REP2), self.assertRaises(frappe.PermissionError):
			request.replace_matches(rows)
		with as_user(REP):
			with self.assertRaises(ValueError):
				request.replace_matches([{**rows[0], "parent": "x"}])
			request.reload()
			request.replace_matches(rows)
			request.set_match_exclusions([("CRM Deal", deal.name)])
			with self.assertRaises(ValueError):
				request.set_match_exclusions([("CRM Deal", "not-a-match")])
		request.reload()
		self.assertEqual([(m.ref_name, m.excluded) for m in request.matches], [(deal.name, 1)])
		with as_user(REP):
			request.submit_for_approval()
			with self.assertRaises(frappe.PermissionError):
				request.replace_matches([])  # after Draft only a decider may refresh matches
		with as_user(PO):
			request.reload()
			request.replace_matches([])
		self.assertEqual(frappe.db.count("CRM Erasure Match", {"parent": request.name}), 0)

	def test_client_normalized_identifier_is_dropped(self):
		request = self.log(identifiers=[{"kind": "Email", "value": "a@x.com", "normalized": "b@x.com"}])
		self.assertFalse(request.identifiers[0].normalized)
		frappe.db.set_value("Contact", self.contact.name, "email_id", "a@x.com")  # on the source
		with as_user(REP):
			request.set_identifiers([{"kind": "Email", "value": "A@x.com", "normalized": "a@x.com"}])
		request.reload()
		self.assertEqual(request.identifiers[0].normalized, "a@x.com")

	def test_only_requester_edits_draft_content(self):
		"""M1: a PO must not rewrite someone else's Draft and then approve it"""
		request = self.log()
		with as_user(PO), self.assertRaises(frappe.ValidationError):
			request.reload()
			request.subject_name = "Rewritten"
			request.save()
		with as_user(PO):
			request.reload()
			request.acknowledged_on = today()
			request.save()
		self.assertEqual(db_value(request, "subject_name"), "Dana Test")

	def test_source_must_exist_and_be_readable(self):
		"""M2"""
		with self.assertRaises(frappe.ValidationError):
			with as_user(REP):
				make_request("Contact", "no-such-contact")
		lead = make_lead("Hidden", lead_owner=None)  # a Sales User reads only own/assigned leads
		other = make_lead("Visible", lead_owner=REP2)
		with as_user(REP2):
			self.assertFalse(frappe.has_permission("CRM Lead", "read", doc=lead.name))
			with self.assertRaises(frappe.ValidationError):
				make_request("CRM Lead", lead.name)
			make_request("CRM Lead", other.name)  # positive control
		request = self.log()
		with as_user(REP), self.assertRaises(frappe.ValidationError):
			request.source_docname = "no-such-contact"
			request.save()

	def test_decider_cannot_forge_identity_in_memory(self):
		"""N1: a PO who logged the request must not approve it by rewriting requested_by/owner"""
		own = self.log(PO_REP)
		with as_user(PO_REP):
			own.submit_for_approval()
			own.requested_by = own.owner = REP
			with self.assertRaises(frappe.PermissionError):
				own.transition_to("Approved", approver=PO_REP)
		self.assertEqual(db_value(own, "status"), "Pending Approval")
		self.assertEqual(db_value(own, "requested_by"), PO_REP)

	def test_requester_identity_comes_from_the_database(self):
		"""N1 requester side: REP2 must not act on REP's Draft by claiming to be its requester"""
		request = self.log()
		calls = {
			"replace_matches": lambda: request.replace_matches([]),
			"set_identifiers": lambda: request.set_identifiers([{"kind": "Email", "value": "x@x.com"}]),
			"submit_for_approval": request.submit_for_approval,
		}
		for label, call in calls.items():
			with self.subTest(call=label), as_user(REP2):
				request.reload()
				request.requested_by = request.owner = REP2
				with self.assertRaises(frappe.PermissionError):
					call()
		self.assertEqual(db_value(request, "status"), "Draft")
		self.assertEqual(db_value(request, "requested_by"), REP)

	def test_internal_save_rejects_identity_changes(self):
		"""N1 second layer: even a system actor's save may not carry a new requested_by/owner"""
		request = approve(self.submitted_by(REP), PO)
		request.requested_by = request.owner = PO
		with self.assertRaises(frappe.ValidationError):
			request.transition_to("Executed")
		self.assertEqual(db_value(request, "status"), "Approved")

	def submitted_by(self, user):
		request = self.log(user)
		with as_user(user):
			request.submit_for_approval()
		return request
