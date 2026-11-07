# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Leaving On Hold: deal saves and deletes, contact deletes and the daily job. The hooks only queue a per-request
job (M1); the tests run that job right after the write, the way a worker would after the commit."""

from unittest.mock import patch

import frappe

from crm.privacy import on_hold
from crm.privacy.on_hold import recheck_all_on_hold, recheck_request
from crm.privacy.tests.make_test_user import (
	force_request,
	make_contact,
	make_request,
	match_rows,
)
from crm.privacy.tests.test_on_hold import CONTACT, DEAL, PERSONAL, OnHoldCase, notices

RECHECK = "crm.privacy.on_hold.recheck_request"


def run_queued(enqueue) -> None:
	"""Run the per-request jobs a hook queued, as a worker would after the commit."""
	for call in enqueue.call_args_list:
		if (call.args[:1] or [None])[0] == RECHECK:
			recheck_request(call.kwargs["request"])


class TestLeavingOnHold(OnHoldCase):
	def setUp(self):
		super().setUp()
		self.submit()
		self.before = self.stored()

	def save_deal(self, **changes):
		deal = frappe.get_doc(DEAL, self.person.negotiation)
		deal.update(changes)
		with patch("frappe.enqueue") as enqueue:
			deal.save()
		run_queued(enqueue)

	def assert_status(self, status):
		self.assertEqual(frappe.db.get_value("CRM Erasure Request", self.name, "status"), status)

	def test_removing_her_contact_row_releases_the_request(self):
		self.save_deal(contacts=[])
		self.assert_status("Awaiting sign-off")
		self.assertEqual(
			match_rows(self.name)[(DEAL, self.person.negotiation)].relation, "Removed from open deal"
		)

	def test_compliance_is_told_without_personal_data_when_the_job_releases_the_request(self):
		self.save_deal(contacts=[])
		(note,) = notices(self.compliance, reference_name=self.name)
		self.assertIn("awaits sign-off", note.notification_text)
		for fragment in PERSONAL:
			self.assertNotIn(fragment, note.notification_text)

	def test_closing_the_deal_with_her_still_on_it_releases_it_but_does_not_confirm_it(self):
		"""[I2] The closed deal stays an unconfirmed suggestion; phase 05 erases her contact copy on it anyway."""
		self.save_deal(status="Won")
		self.assert_status("Awaiting sign-off")
		row = match_rows(self.name)[(DEAL, self.person.negotiation)]
		self.assertEqual((row.relation, row.confirmed), ("Linked", 0))

	def test_closing_a_deal_the_logger_had_confirmed_keeps_it_confirmed(self):
		self.submit_confirmed_hold = None
		frappe.db.set_value(
			"CRM Erasure Match", match_rows(self.name)[(DEAL, self.person.negotiation)].name, "confirmed", 1
		)
		self.save_deal(status="Won")
		self.assert_status("Awaiting sign-off")
		row = match_rows(self.name)[(DEAL, self.person.negotiation)]
		self.assertEqual((row.relation, row.confirmed), ("Direct", 1))

	def test_a_deal_edit_that_changes_nothing_relevant_keeps_the_hold(self):
		self.save_deal(status="Proposal/Quotation")
		self.assert_status("On Hold")

	def test_the_deadline_is_unchanged_throughout(self):
		self.save_deal(status="Won")
		after = self.stored()
		self.assertEqual(
			(after.respond_by, after.acknowledge_by), (self.before.respond_by, self.before.acknowledge_by)
		)

	def test_deleting_the_open_deal_releases_the_request(self):
		with patch("frappe.enqueue") as enqueue:
			frappe.delete_doc(DEAL, self.person.negotiation, force=True)
		run_queued(enqueue)
		self.assert_status("Awaiting sign-off")
		self.assertNotIn((DEAL, self.person.negotiation), match_rows(self.name))

	def test_deleting_her_contact_re_evaluates_the_request(self):
		with patch("frappe.enqueue") as enqueue:
			frappe.delete_doc(CONTACT, self.person.contact, force=True)
		run_queued(enqueue)
		self.assert_status("Awaiting sign-off")

	def test_deleting_a_contact_that_is_not_confirmed_leaves_the_hold(self):
		unrelated = make_contact("Unrelated", emails=["u@example.com"], last_name="Else")
		with patch("frappe.enqueue") as enqueue:
			frappe.delete_doc(CONTACT, unrelated, force=True)
		self.assertEqual([c for c in enqueue.call_args_list if c.args[:1] == (RECHECK,)], [])
		self.assert_status("On Hold")

	def test_the_daily_job_releases_a_request_whose_deal_changed_by_a_raw_write(self):
		frappe.db.set_value(DEAL, self.person.negotiation, "status", "Won")
		self.assert_status("On Hold")
		recheck_all_on_hold()
		self.assert_status("Awaiting sign-off")
		self.assertEqual(len(notices(self.compliance, reference_name=self.name)), 1)

	def test_the_daily_job_tolerates_a_deal_deleted_by_a_raw_write(self):
		frappe.db.delete(DEAL, {"name": self.person.negotiation})
		recheck_all_on_hold()
		self.assert_status("Awaiting sign-off")
		self.assertNotIn((DEAL, self.person.negotiation), match_rows(self.name))

	def test_the_daily_job_picks_up_a_new_open_deal_and_notifies_its_owner_once(self):
		frappe.db.set_value(DEAL, self.person.negotiation, "status", "Won")
		recheck_all_on_hold()
		frappe.db.set_value("CRM Erasure Request", self.name, "status", "On Hold")
		frappe.db.set_value(DEAL, self.person.negotiation, "status", "Negotiation")
		recheck_all_on_hold()
		recheck_all_on_hold()
		self.assert_status("On Hold")
		self.assertEqual(len(notices(self.other, reference_name=self.person.negotiation)), 1)

	def test_the_daily_job_leaves_a_frozen_request_alone(self):
		force_request(self.name, erasure_job_status="Running")
		frappe.db.set_value(DEAL, self.person.negotiation, "status", "Won")
		recheck_all_on_hold()
		self.assert_status("On Hold")

	def test_the_daily_job_keeps_going_after_one_request_fails(self):
		second = make_request(self.manager, source_doctype=CONTACT, source_name=self.person.contact)
		self.submit(second)
		frappe.db.set_value(DEAL, self.person.negotiation, "status", "Won")
		real = on_hold.evaluate_hold

		def flaky(doc, **kwargs):
			if doc.name == self.name:
				raise RuntimeError("boom")
			return real(doc, **kwargs)

		with patch("crm.privacy.on_hold.evaluate_hold", flaky):
			recheck_all_on_hold()
		self.assert_status("On Hold")
		self.assertEqual(frappe.db.get_value("CRM Erasure Request", second, "status"), "Awaiting sign-off")
