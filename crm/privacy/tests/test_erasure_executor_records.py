# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The erasure job on her records and what hangs off them: the after-state of design 5.6 (phase 05 steps 3-5, 9)."""

import frappe
from frappe.utils import cstr

from crm.privacy.tests.erasure_run_case import ExecutorCase

DEAL_FIELDS = (
	"status",
	"deal_value",
	"deal_owner",
	"source",
	"territory",
	"closed_date",
	"creation",
	"modified",
)


class RecordsCase(ExecutorCase):
	def setUp(self):
		super().setUp()
		self.person = f"Erased person {self.request}"
		self.content = f"Content erased {self.request}"
		self.deal_before = {
			name: self.values("CRM Deal", name, *DEAL_FIELDS)
			for name in (self.p.won, self.p.copy_deal, self.p.removed)
		}
		self.lead_before = self.values(
			"CRM Lead", self.p.lead, "status", "lead_owner", "creation", "modified"
		)
		self.approve_and_run()

	def assertBlank(self, doctype, name, *fields):
		for field, value in self.values(doctype, name, *fields).items():
			self.assertFalse(value, f"{doctype} {name} {field} = {value!r}")


class TestRecords(RecordsCase):
	def test_the_request_is_erased(self):
		stored = self.stored("status", "erasure_job_status", "erasure_error", "erased_on", "approver")
		self.assertEqual(stored.status, "Erased")
		self.assertFalse(stored.erasure_job_status or stored.erasure_error)
		self.assertTrue(stored.erased_on)
		self.assertEqual(stored.approver, self.compliance)

	def test_her_lead_is_a_shell_with_a_placeholder_name(self):
		lead = self.values("CRM Lead", self.p.lead, "first_name", "lead_name", "personal_mobile")
		self.assertEqual((lead.first_name, lead.lead_name), (self.person, self.person))
		self.assertBlank(
			"CRM Lead", self.p.lead, "last_name", "email", "mobile_no", "phone", "job_title", "image"
		)
		self.assertEqual(lead.personal_mobile, "+15305550104")  # a gap Compliance was shown, not on the list
		after = self.values("CRM Lead", self.p.lead, "status", "lead_owner", "creation", "modified")
		self.assertEqual(after, self.lead_before)

	def test_her_contact_is_blanked_renamed_and_loses_its_rows(self):
		self.assertFalse(frappe.db.exists("Contact", self.p.contact))
		contact = self.values("Contact", self.person, "first_name", "full_name")
		self.assertEqual((contact.first_name, contact.full_name), (self.person, self.person))
		self.assertBlank("Contact", self.person, "last_name", "email_id", "mobile_no", "designation", "image")
		self.assertEqual(frappe.db.count("Contact Email", {"parent": self.person}), 0)
		self.assertEqual(frappe.db.count("Contact Phone", {"parent": self.person}), 0)

	def test_her_address_is_blanked_and_renamed(self):
		self.assertFalse(frappe.db.exists("Address", self.p.address))
		address = self.values("Address", self.person, "address_title", "country")
		self.assertEqual(address.address_title, self.person)
		self.assertEqual(address.country, "United States")
		self.assertBlank("Address", self.person, "address_line1", "city", "email_id", "phone")

	def test_the_deals_she_is_on_keep_their_numbers_and_lose_her_row(self):
		for name in (self.p.won, self.p.copy_deal, self.p.removed):
			self.assertEqual(self.values("CRM Deal", name, *DEAL_FIELDS), self.deal_before[name], name)
		for deal in (self.p.won, self.p.copy_deal):
			row = frappe.get_all(
				"CRM Contacts", {"parent": deal, "contact": self.person},
				["full_name", "email", "mobile_no", "phone", "gender"],
			)  # fmt: skip
			self.assertEqual(len(row), 1, deal)
			self.assertEqual(row[0].full_name, self.person)
			self.assertFalse(row[0].email or row[0].mobile_no or row[0].phone or row[0].gender)

	def test_deal_fields_are_blanked_only_where_they_hold_her_values(self):
		self.assertBlank("CRM Deal", self.p.won, "email", "mobile_no")  # copied from her as primary contact
		copy = self.values("CRM Deal", self.p.copy_deal, "email", "mobile_no")
		self.assertEqual(copy.email, self.p.colleague_email)  # the colleague is primary there
		self.assertEqual(copy.mobile_no, "+15305550177")

	def test_the_colleague_the_stranger_and_the_removed_from_deal_are_untouched(self):
		colleague = self.values("Contact", self.p.colleague, "full_name", "email_id", "mobile_no")
		self.assertEqual((colleague.full_name, colleague.email_id), ("Jon Park", self.p.colleague_email))
		stranger = self.values("CRM Lead", self.p.lookalike, "first_name", "email", "mobile_no")
		self.assertEqual((stranger.email, stranger.mobile_no), ("adam.vega@example.com", "+153055501019"))
		self.assertEqual(frappe.db.count("Contact Email", {"parent": self.p.colleague}), 2)
		rows = frappe.get_all("CRM Contacts", {"parent": self.p.removed}, pluck="full_name")
		self.assertEqual(rows, ["Jon Park"])


class TestEmailsAndCalls(RecordsCase):
	def test_her_emails_keep_their_other_people(self):
		c = self.activity.communications
		lead = self.values("Communication", c.mail_lead, "subject", "content", "sender", "cc", "recipients")
		self.assertEqual((lead.subject, lead.content), (self.content, self.content))
		self.assertEqual(lead.sender, self.person)
		self.assertEqual(lead.cc, self.p.colleague_email)
		self.assertEqual(lead.recipients, self.p.rep_email)
		contact = self.values("Communication", c.mail_contact, "subject", "recipients", "sender")
		self.assertEqual(
			(contact.subject, contact.recipients, contact.sender),
			(self.content, self.person, self.p.rep_email),
		)

	def test_emails_that_are_not_hers_are_untouched(self):
		c = self.activity.communications
		for name in (c.mail_colleague, c.mail_lookalike, c.mail_shared, c.mail_copy_deal):
			self.assertNotEqual(self.values("Communication", name, "subject").subject, self.content, name)

	def test_calls_lose_her_number_and_recording(self):
		c = self.activity.calls
		recorded = self.values("CRM Call Log", c.call_recorded, "from", "to", "recording_url", "status")
		self.assertEqual(recorded["from"], self.person)
		self.assertFalse(recorded.recording_url)
		self.assertEqual(recorded.status, "Completed")
		self.assertEqual(self.values("CRM Call Log", c.call_by_number, "from")["from"], self.person)
		self.assertEqual(self.values("CRM Call Log", c.call_removed, "to")["to"], self.person)
		self.assertEqual(self.values("CRM Call Log", c.call_lookalike, "from")["from"], "+153055501019")


class TestNotesAndFriends(RecordsCase):
	def test_notes_tasks_comments_and_todos_of_her_records_say_content_erased(self):
		n, c = self.activity.notes, self.activity.calls
		for note in (n.note_lead, n.note_contact, n.note_won, c.call_note):
			self.assertEqual(
				list(self.values("FCRM Note", note, "title", "content").values()), [self.content] * 2
			)
		for task in (n.task_lead, n.task_contact, n.task_won):
			row = self.values("CRM Task", task, "title", "description", "status")
			self.assertEqual((row.title, row.description, row.status), (self.content, self.content, "Todo"))
		for todo in (n.todo_lead, n.todo_contact, n.todo_won):
			row = self.values("ToDo", todo, "description", "allocated_to")
			self.assertEqual((row.description, row.allocated_to), (self.content, self.p.rep))
		for comment in (n.comment_lead, n.comment_contact, n.comment_won):
			self.assertEqual(
				self.values("Comment", comment, "content", "comment_type"),
				{"content": self.content, "comment_type": "Comment"},
			)

	def test_every_comment_type_on_her_records_is_scrubbed(self):  # [I4]
		rows = frappe.get_all(
			"Comment", {"reference_doctype": "CRM Lead", "reference_name": self.p.lead},
			["comment_type", "content"],
		)  # fmt: skip
		self.assertGreater(len({r.comment_type for r in rows}), 1)
		for row in rows:
			self.assertIn(cstr(row.content), (self.content, f"File erased {self.request}"), row.comment_type)

	def test_what_belongs_to_the_deal_she_was_removed_from_stays(self):
		n = self.activity.notes
		self.assertIn("Marisol", self.values("FCRM Note", n.note_removed, "content").content)
		self.assertIn("Call Marisol", self.values("CRM Task", n.task_removed, "description").description)
		self.assertIn("agreed", self.values("Comment", n.comment_removed, "content").content)
		self.assertIn("quote", self.values("ToDo", n.todo_removed, "description").description)
		self.assertIn("Marisol", self.values("FCRM Note", n.note_copy, "content").content)
