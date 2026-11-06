# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from itertools import product

from frappe.tests import UnitTestCase

from crm.fcrm.doctype.crm_erasure_request.erasure_states import (
	can_decide,
	can_transition,
	transition_actor,
)

STATUSES = ["Draft", "Pending Approval", "On Hold", "Approved", "Executed", "Closed", "Rejected"]
EXPECTED = {
	("Draft", "Pending Approval"): "requester",
	("Draft", "On Hold"): "requester",
	("Pending Approval", "On Hold"): "system",
	("On Hold", "Pending Approval"): "system",
	("Pending Approval", "Approved"): "decider",
	("Approved", "Executed"): "system",
	("Executed", "Closed"): "privacy_officer",
	("Draft", "Rejected"): "decider",
	("Pending Approval", "Rejected"): "decider",
	("On Hold", "Rejected"): "decider",
}


class TestErasureStates(UnitTestCase):
	def test_every_status_pair(self):
		for from_status, to_status in product([*STATUSES, None, "Bogus"], STATUSES):
			with self.subTest(from_status=from_status, to_status=to_status):
				expected = EXPECTED.get((from_status, to_status))
				self.assertEqual(can_transition(from_status, to_status), expected is not None)
				self.assertEqual(transition_actor(from_status, to_status), expected)

	def test_can_decide(self):
		po = ["Sales User", "Privacy Officer"]
		cases = [
			("po@x.com", po, "rep@x.com", "rep@x.com", True),  # positive control
			("rep@x.com", po, "rep@x.com", "rep@x.com", False),  # self-approval
			("po@x.com", po, "rep@x.com", "po@x.com", False),  # owner is the approver
			("po@x.com", po, "po@x.com", "rep@x.com", False),  # requester is the approver
			("mgr@x.com", ["Sales Manager", "Sales User"], "rep@x.com", "rep@x.com", False),
			("sys@x.com", ["System Manager"], "rep@x.com", "rep@x.com", False),
			("", po, "rep@x.com", "rep@x.com", False),
			("Guest", po, "rep@x.com", "rep@x.com", False),
		]
		for user, roles, requested_by, owner, expected in cases:
			with self.subTest(user=user, roles=roles, requested_by=requested_by, owner=owner):
				self.assertEqual(can_decide(user, roles, requested_by, owner), expected)
