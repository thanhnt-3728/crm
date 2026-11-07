# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The approved-plan hash [RT-1], the open-deal invariant [RT-2] and dangling matches (phase 05 step 4)."""

import frappe

from crm.api.erasure_requests import set_identifier_excluded
from crm.privacy.erasure.plan import ErasureHoldError
from crm.privacy.erasure.plan_builder import build_plan
from crm.privacy.tests.erasure_fixture import ErasureTestCase
from crm.privacy.tests.erasure_fixture_mail import mail
from crm.privacy.tests.make_test_user import as_user, make_contact, make_lead

DOCTYPE = "CRM Erasure Request"


class HashCase(ErasureTestCase):
	def plan(self, **kwargs):
		return build_plan(frappe.get_doc(DOCTYPE, self.request), **kwargs)


class TestPlanHash(HashCase):
	def test_the_hash_is_a_stable_sha256_of_the_plan(self):
		first = self.plan().hash()
		self.assertRegex(first, r"^[0-9a-f]{64}$")
		self.assertEqual(self.plan().hash(), first)

	def test_an_unrelated_record_does_not_change_it(self):
		before = self.plan().hash()
		make_lead(first_name="Adam", last_name="Other", email="adam.other@example.com")
		mail(self.p, "someone.else@example.com", subject="Hi", content="Hello")
		self.assertEqual(self.plan().hash(), before)

	def test_a_new_email_from_her_changes_it(self):
		before = self.plan().hash()
		mail(self.p, self.p.email, subject="Me again", content="Where is my data")
		self.assertNotEqual(self.plan().hash(), before)

	def test_a_target_that_disappears_changes_it(self):
		before = self.plan().hash()
		frappe.delete_doc("Comment", self.activity.notes.comment_lead, force=True, ignore_permissions=True)
		self.assertNotEqual(self.plan().hash(), before)

	def edit_match(self, record, confirmed):
		match = {"parent": self.request, "reference_name": record}
		frappe.db.set_value("CRM Erasure Match", match, "confirmed", confirmed)

	def test_confirming_a_match_behind_the_api_changes_it(self):
		before = self.plan().hash()
		self.edit_match(self.p.copy_deal, 1)  # from a contact copy to a deal she is on: its notes now go too
		self.assertNotEqual(self.plan().hash(), before)

	def test_unconfirming_a_match_behind_the_api_changes_it(self):
		before = self.plan().hash()
		self.edit_match(self.p.contact, 0)
		self.assertNotEqual(self.plan().hash(), before)

	def test_excluding_or_keeping_an_identifier_changes_it(self):
		before = self.plan().hash()
		row = next(
			i.name for i in frappe.get_doc(DOCTYPE, self.request).identifiers if i.value == self.p.email2
		)
		as_user(self.compliance, set_identifier_excluded, self.request, row, True)
		self.assertNotEqual(self.plan().hash(), before)

	def test_the_order_of_rows_does_not_matter(self):
		doc = frappe.get_doc(DOCTYPE, self.request)
		reordered = build_plan(doc)
		for kind in reordered.targets:
			reordered.targets[kind] = list(reversed(reordered.targets[kind]))
		self.assertEqual(reordered.hash(), self.plan().hash())


class TestOpenDealInvariant(HashCase):
	def test_a_deal_she_is_still_on_that_is_open_raises(self):
		frappe.db.set_value("CRM Deal", self.p.won, "status", "Negotiation")
		with self.assertRaises(ErasureHoldError):
			self.plan()

	def test_a_contact_copy_deal_that_is_open_raises(self):
		frappe.db.set_value("CRM Deal", self.p.copy_deal, "status", "Negotiation")
		with self.assertRaises(ErasureHoldError):
			self.plan()

	def test_the_preview_can_still_read_the_plan_and_names_the_open_deals(self):
		frappe.db.set_value("CRM Deal", self.p.won, "status", "Negotiation")
		plan = self.plan(check_hold=False)
		self.assertEqual(plan.open_deals, [self.p.won])
		self.assertEqual(plan.targets["deals_on"], [self.p.won])

	def test_an_open_deal_she_was_removed_from_is_allowed(self):
		self.assertEqual(frappe.db.get_value("CRM Deal", self.p.removed, "status"), "Negotiation")
		self.assertEqual(self.plan().targets["deals_removed"], [self.p.removed])


class TestDanglingAndNewMatches(HashCase):
	def test_a_confirmed_record_deleted_before_approval_is_tolerated(self):
		frappe.delete_doc("CRM Deal", self.p.won, force=True, ignore_permissions=True)
		plan = self.plan()
		self.assertEqual(plan.targets["deals_on"], [])
		self.assertIn(("CRM Deal", self.p.won), plan.gone)
		mine = frappe.get_all(
			"Deleted Document", {"deleted_name": self.p.won}, pluck="name", order_by="creation desc"
		)
		self.assertIn(
			mine[0], plan.targets["deleted_documents"]
		)  # (names repeat across test runs: take the newest)

	def test_a_contact_the_mailbox_made_for_her_address_is_not_in_the_plan(self):
		new = make_contact("Marisol", emails=[self.p.email], last_name="Vega Jr")
		self.assertNotIn(new, self.plan().targets["contacts"])
