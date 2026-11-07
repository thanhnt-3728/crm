# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Change history after an erasure: hers is gone, everyone else's stays (review H1, H2, H4)."""

import json

import frappe

from crm.privacy.tests.erasure_fixture_extras import version
from crm.privacy.tests.erasure_run_case import ExecutorCase

COLLEAGUE = "jon.park@sierra.example.com"
KEPT = ("Jon Park", COLLEAGUE, "jon.old@sierra.example.com", "jon.p@sierra.example.com", "+15305550177")


class HistoryCase(ExecutorCase):
	def setUp(self):
		super().setUp()
		self.person = f"Erased person {self.request}"
		self.copy_version = version(
			"CRM Deal",
			self.p.copy_deal,
			{"changed": [["gender", "", "Female"], ["job_title", "", "Practice manager"]]},
		)
		self.approve_and_run()

	def data(self, name: str) -> str:
		return frappe.db.get_value("Version", name, "data")


class TestColleaguesSurvive(HistoryCase):
	def test_the_colleagues_names_and_emails_in_a_deals_history_are_kept(self):
		e = self.activity.extras
		for name in (e.colleague_version_removed, e.colleague_version_won):
			text = self.data(name)
			for kept in KEPT:
				self.assertIn(kept, text, f"{kept} lost from {name}")

	def test_only_her_row_and_her_values_in_that_history_are_replaced(self):
		for name in (
			self.activity.extras.colleague_version_removed,
			self.activity.extras.colleague_version_won,
		):
			data = json.loads(self.data(name))
			text = json.dumps(data)
			for hers in (self.p.email, "Marisol Vega", self.p.phone):
				self.assertNotIn(hers, text, hers)
			colleague = [row for _t, row in data["added"] if row.get("contact") == self.p.colleague]
			self.assertEqual(len(colleague), 1)
			self.assertEqual(colleague[0]["full_name"], "Jon Park")
			hers = [row for _t, row in data["added"] if row.get("full_name") == self.person]
			self.assertEqual(hers, [{"contact": self.person, "full_name": self.person, "email": self.person,
				"mobile_no": self.person, "idx": 1}])  # fmt: skip
			self.assertEqual(data["changed"][0], ["email", "jon.old@sierra.example.com", COLLEAGUE])

	def test_the_earlier_probe_the_deals_value_changes_keep_other_peoples_emails(self):
		# the fixture's own deal history (`add_deal_version`) changed the email from old@example.com to hers
		texts = frappe.get_all("Version", {"docname": self.p.won, "ref_doctype": "CRM Deal"}, pluck="data")
		self.assertTrue(any("old@example.com" in t for t in texts), "the previous value was lost")


class TestWordsThatCoincide(HistoryCase):
	def test_a_colleagues_deal_keeps_gender_salutation_and_job_title(self):
		for deal in (self.p.copy_deal, self.p.won):
			row = self.values("CRM Deal", deal, "gender", "salutation", "job_title")
			self.assertEqual(list(row.values()), ["Female", "Ms", "Practice manager"], deal)

	def test_her_own_lead_is_blanked_in_those_fields(self):
		for field in ("gender", "salutation", "job_title"):
			self.assertFalse(self.values("CRM Lead", self.p.lead, field)[field])

	def test_the_same_words_in_the_colleagues_deal_history_stay(self):
		self.assertEqual(
			json.loads(self.data(self.copy_version))["changed"],
			[["gender", "", "Female"], ["job_title", "", "Practice manager"]],
		)


class TestActivityHistory(HistoryCase):
	def test_note_todo_and_event_versions_lose_her_text(self):
		e = self.activity.extras
		self.assertNotIn("Marisol", self.data(e.version_note))
		self.assertNotIn("5305550101", self.data(e.version_note))
		self.assertNotIn(self.p.email, self.data(e.version_todo))
		self.assertNotIn("Marisol Vega", self.data(e.version_event))

	def test_every_version_of_a_target_with_edit_history_is_covered(self):
		for doctype, names in (
			("FCRM Note", [self.activity.notes.note_lead, self.activity.notes.note_contact]),
			("ToDo", [self.activity.notes.todo_lead]),
		):
			for text in frappe.get_all(
				"Version", {"ref_doctype": doctype, "docname": ["in", names]}, pluck="data"
			):
				self.assertNotIn("Marisol", text, doctype)
