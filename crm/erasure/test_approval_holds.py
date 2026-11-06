# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe

from crm.api import erasure as api
from crm.erasure.erasure_test_fixture_base import OPEN_STATUS
from crm.erasure.erasure_test_fixture_execution import REQUEST, her_identifier_strings, pending_marisol_request
from crm.erasure.erasure_test_fixtures import HER_EMAILS, raw_insert
from crm.erasure.registry_model import name_marker
from crm.erasure.test_approval import ApprovalCase
from crm.fcrm.doctype.crm_erasure_request.erasure_test_fixtures import PO, REP, as_user


class TestApprovalHolds(ApprovalCase):
	def test_open_deal_found_only_by_rediscovery_holds_the_approval(self):
		request = pending_marisol_request(self.fx)
		deal = {"doctype": "CRM Deal", "status": OPEN_STATUS, "deal_owner": REP, "email": HER_EMAILS[0]}
		new_deal = raw_insert(deal).name  # linked to nothing of hers: only her email finds it
		with self.assertRaises(frappe.ValidationError):
			self.approve(request)  # the preview it confirms already lists the deal
		state = frappe.db.get_value(REQUEST, request.name, ["status", "hold_reason"], as_dict=True)
		self.assertEqual(state.status, "On Hold")
		self.assertIn(new_deal, state.hold_reason)
		self.enqueue.assert_not_called()

	def test_reject_applies_retention(self):
		request = pending_marisol_request(self.fx)
		with as_user(PO):
			api.reject(request.name, "Identity not verified")
		rejected = frappe.get_doc(REQUEST, request.name)
		self.assertEqual((rejected.status, rejected.subject_name), ("Rejected", name_marker(request.name)))
		stored = frappe.as_json([row.as_dict() for row in rejected.identifiers]).lower()
		for text in her_identifier_strings()[:4]:
			self.assertNotIn(text.lower(), stored)
		self.assertEqual(rejected.rejection_reason, "Identity not verified")
