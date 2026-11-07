# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Phase 07 fix round: `owner_name` on the match rows that hold a request, and the `set_contract_references` flag."""

import frappe

from crm.api.erasure_requests import get_request, request_response, submit_request
from crm.api.erasure_review import set_contract_references
from crm.privacy.request_status import ALLOWED
from crm.privacy.request_visibility import available_actions
from crm.privacy.tests.make_test_user import (
	RequestTestCase,
	as_user,
	force_request,
	make_person,
	make_request,
)

DEAL, CONTACT = "CRM Deal", "Contact"


class TestHoldDealOwnerName(RequestTestCase):
	def setUp(self):
		super().setUp()
		self.person = make_person(owner=self.other)
		self.name = make_request(self.manager, source_doctype=CONTACT, source_name=self.person.contact)
		as_user(self.manager, submit_request, self.name)  # the Negotiation deal holds it: On Hold

	def rows(self, user=None):
		data = as_user(user or self.compliance, get_request, self.name)
		return {(m.reference_doctype, m.reference_name): m for m in data["matches"]}

	def test_the_holding_deal_row_carries_the_owners_full_name(self):
		row = self.rows()[(DEAL, self.person.negotiation)]
		self.assertEqual(row.get("owner_name"), frappe.db.get_value("User", self.other, "full_name"))

	def test_other_rows_carry_no_owner_name(self):
		for key, row in self.rows().items():
			if key != (DEAL, self.person.negotiation):
				self.assertFalse(row.get("owner_name"), key)

	def test_a_sales_manager_sees_it_too(self):
		row = self.rows(self.manager)[(DEAL, self.person.negotiation)]
		self.assertTrue(row.get("owner_name"))

	def test_no_name_once_the_request_is_not_on_hold(self):
		force_request(self.name, status="Awaiting sign-off")
		frappe.db.set_value("CRM Deal", self.person.negotiation, "status", "Won")
		self.assertTrue(all(not m.get("owner_name") for m in self.rows().values()))

	def test_a_viewer_who_cannot_read_the_deal_gets_neither_row_nor_name(self):
		doc = frappe.get_doc("CRM Erasure Request", self.name)
		frappe.set_user(self.logger)  # sees no deal he neither owns nor was assigned
		try:
			if frappe.has_permission(DEAL, "read", self.person.negotiation):
				self.skipTest("a Sales User can read every deal on this site")
			matches = request_response(doc)["matches"]
		finally:
			frappe.set_user("Administrator")
		self.assertNotIn(self.person.negotiation, [m.reference_name for m in matches])
		self.assertFalse(any(m.get("owner_name") for m in matches))


class TestSetContractReferencesFlag(RequestTestCase):
	"""The flag is true exactly when `set_contract_references` would accept the call."""

	def attempt(self, name: str, user: str) -> bool:
		try:
			as_user(user, set_contract_references, name, ["CT-1"])
		except (frappe.PermissionError, frappe.ValidationError):
			return False
		return True

	def test_the_flag_and_the_endpoint_agree(self):
		users = {
			"compliance": self.compliance,
			"manager": self.manager,
			"logger": self.logger,
			"other": self.other,
			"admin": "Administrator",
		}
		checked = 0
		for status in ALLOWED:
			for job in ("", "Queued", "Running", "Failed"):
				name = self.submitted_request(status=status)
				force_request(name, erasure_job_status=job)
				doc = frappe.get_doc("CRM Erasure Request", name)
				for label, user in users.items():
					flag = available_actions(doc, user).get("set_contract_references")
					with self.subTest(status=status, job=job, user=label):
						self.assertIsNotNone(flag, "the flag is missing")
						self.assertEqual(flag, self.attempt(name, user))
					checked += 1
		self.assertEqual(checked, len(ALLOWED) * 4 * len(users))

	def test_only_compliance_before_the_erasure_gets_it(self):
		name = self.submitted_request(status="Awaiting sign-off")
		self.assertTrue(as_user(self.compliance, get_request, name)["can"].get("set_contract_references"))
		doc = frappe.get_doc("CRM Erasure Request", name)
		for user in (self.manager, self.logger, "Administrator"):
			self.assertFalse(available_actions(doc, user).get("set_contract_references"))
