# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase

from crm.fcrm.doctype.crm_erasure_request.erasure_test_fixtures import (
	PO,
	REP,
	approve,
	as_user,
	ensure_users,
	make_contact,
	make_deal,
	make_lead,
	make_request,
)


class TestErasureDeleteGuard(IntegrationTestCase):
	def setUp(self):
		ensure_users()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def log(self, source_doctype, source_docname, matches=()):
		with as_user(REP):
			return make_request(source_doctype, source_docname, matches)

	def assert_delete_blocked(self, doctype, name, request):
		with self.assertRaises(frappe.ValidationError) as ctx:
			frappe.delete_doc(doctype, name)
		self.assertIn(request.name, str(ctx.exception))
		self.assertTrue(frappe.db.exists(doctype, name))

	def test_source_of_draft_request_cannot_be_deleted(self):
		lead = make_lead()
		request = self.log("CRM Lead", lead.name)
		self.assert_delete_blocked("CRM Lead", lead.name, request)

	def test_matched_deal_of_pending_request_cannot_be_deleted(self):
		contact = make_contact()
		deal = make_deal()
		deal.db_set("status", "Lost")  # a closed deal does not hold the request
		request = self.log("Contact", contact.name, matches=[("CRM Deal", deal.name)])
		with as_user(REP):
			request.submit_for_approval()
		self.assertEqual(request.status, "Pending Approval")
		self.assert_delete_blocked("CRM Deal", deal.name, request)
		self.assert_delete_blocked("Contact", contact.name, request)

	def test_approved_request_blocks_and_executed_releases(self):
		contact = make_contact()
		request = self.log("Contact", contact.name)
		with as_user(REP):
			request.submit_for_approval()
		approve(request, PO)
		self.assert_delete_blocked("Contact", contact.name, request)
		request.reload()
		request.transition_to("Executed", executed_on=frappe.utils.now_datetime())
		frappe.delete_doc("Contact", contact.name)
		self.assertFalse(frappe.db.exists("Contact", contact.name))

	def test_rejected_request_releases(self):
		lead = make_lead()
		request = self.log("CRM Lead", lead.name)
		with as_user(PO):
			request.reload()
			request.transition_to("Rejected", rejection_reason="Duplicate")
		frappe.delete_doc("CRM Lead", lead.name)
		self.assertFalse(frappe.db.exists("CRM Lead", lead.name))

	def test_excluded_match_and_unrelated_docs_can_be_deleted(self):
		contact = make_contact()
		excluded = make_deal()
		unrelated = make_lead("Unrelated")
		self.log("Contact", contact.name, matches=[("CRM Deal", excluded.name, 1)])
		frappe.delete_doc("CRM Deal", excluded.name)
		frappe.delete_doc("CRM Lead", unrelated.name)
		self.assertFalse(frappe.db.exists("CRM Deal", excluded.name))
		self.assertFalse(frappe.db.exists("CRM Lead", unrelated.name))

	def test_rename_of_referenced_docs_is_blocked_while_open(self):
		"""H1: renaming must not let the record slip out from under the delete guard"""
		lead = make_lead()
		deal = make_deal()
		request = self.log("CRM Lead", lead.name, matches=[("CRM Deal", deal.name)])
		for doctype, name in (("CRM Lead", lead.name), ("CRM Deal", deal.name)):
			with self.subTest(doctype=doctype):
				with self.assertRaises(frappe.ValidationError) as ctx:
					frappe.rename_doc(doctype, name, f"{name}-renamed", force=True)
				self.assertIn(request.name, str(ctx.exception))
				self.assertTrue(frappe.db.exists(doctype, name))
		self.assert_delete_blocked("CRM Lead", lead.name, request)

	def test_rename_after_rejection_is_followed_by_the_request(self):
		lead = make_lead()
		deal = make_deal()
		request = self.log("CRM Lead", lead.name, matches=[("CRM Deal", deal.name)])
		with as_user(PO):
			request.reload()
			request.transition_to("Rejected", rejection_reason="Duplicate")
		frappe.rename_doc("CRM Lead", lead.name, f"{lead.name}-r", force=True)
		frappe.rename_doc("CRM Deal", deal.name, f"{deal.name}-r", force=True)
		request.reload()
		self.assertEqual(request.source_docname, f"{lead.name}-r")
		self.assertEqual(request.matches[0].ref_name, f"{deal.name}-r")
