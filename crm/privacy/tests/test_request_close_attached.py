# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""What closing does to the emails, files and comments attached to the request (phase 06; RT-8, RT-12)."""

import os

import frappe

from crm.privacy.tests.close_fixture import EMAIL, OTHER, CloseTestCase

COMMUNICATION = "Communication"
COLUMNS = ["subject", "content", "text_content", "sender", "recipients", "sender_full_name", "reference_doctype", "reference_name"]  # fmt: skip


class TestEmailsAttachedToTheRequest(CloseTestCase):
	def mail_row(self, name):
		return frappe.db.get_value(COMMUNICATION, name, COLUMNS, as_dict=True)

	def test_inbound_mail_is_scrubbed_and_detached(self):
		self.close()
		row = self.mail_row(self.mail)
		self.assertEqual(row.subject, f"Content erased {self.request}")
		self.assertEqual(row.content, f"Content erased {self.request}")
		self.assertEqual(row.text_content, f"Content erased {self.request}")
		self.assertEqual(row.sender, f"Erased person {self.request}")
		self.assertEqual(row.sender_full_name, f"Erased person {self.request}")
		self.assertFalse(row.reference_doctype or row.reference_name)

	def test_the_outcome_email_loses_her_address_but_keeps_other_recipients(self):
		self.close()
		row = self.mail_row(self.sent)
		self.assertNotIn(EMAIL, row.recipients)
		self.assertIn(f"Erased person {self.request}", row.recipients)
		self.assertIn(OTHER, row.recipients)
		self.assertEqual(row.content, f"Content erased {self.request}")
		self.assertFalse(row.reference_doctype or row.reference_name)

	def test_nothing_links_to_the_request_any_more(self):
		self.close()
		for doctype, field in (
			(COMMUNICATION, "reference_name"),
			("Communication Link", "link_name"),
			("File", "attached_to_name"),
			("Email Queue", "reference_name"),
		):
			self.assertEqual(frappe.db.count(doctype, {field: self.request}), 0, doctype)

	def test_an_unrelated_email_is_left_alone(self):
		from crm.privacy.tests.inbound_helpers import incoming_email

		other = incoming_email("someone@else.example", None, subject="Unrelated", content="Keep me")
		other.insert(ignore_permissions=True)
		self.close()
		self.assertEqual(self.mail_row(other.name).content, "Keep me")

	def test_the_emails_are_kept_as_rows(self):
		self.close()
		self.assertTrue(frappe.db.exists(COMMUNICATION, self.mail))
		self.assertTrue(frappe.db.exists(COMMUNICATION, self.sent))


class TestFilesCommentsAndQueuedMail(CloseTestCase):
	def test_file_rows_go_at_once_and_bytes_only_after_the_commit(self):
		self.close()
		for doc in (self.file, self.mail_file):
			self.assertFalse(frappe.db.exists("File", doc.name))
			self.assertTrue(self.bytes_exist(doc), "bytes must outlive the transaction")
		self.assertIn(self.file.file_url, self.stored("pending_file_deletions").pending_file_deletions)
		self.finish_after_commit()
		for doc in (self.file, self.mail_file):
			self.assertFalse(self.bytes_exist(doc))
		self.assertFalse(self.stored("pending_file_deletions").pending_file_deletions)

	def test_a_file_shared_with_another_row_keeps_its_bytes(self):
		from crm.privacy.tests.erasure_fixture_files import file_doc

		keeper = file_doc(
			"CRM Lead", frappe.get_all("CRM Lead", pluck="name", limit=1)[0], "x.txt", content="same"
		)
		mine = file_doc("CRM Erasure Request", self.request, "y.txt", content="same")
		self.assertEqual(keeper.file_url, mine.file_url)
		self.close()
		self.finish_after_commit()
		self.assertTrue(self.bytes_exist(keeper))

	def test_the_sweeper_state_is_cleared_even_when_the_bytes_are_already_gone(self):
		self.close()
		os.remove(self.file.get_full_path())
		self.finish_after_commit()
		self.assertFalse(self.stored("pending_file_deletions").pending_file_deletions)

	def test_every_comment_on_the_request_loses_its_text_whatever_its_type(self):
		self.close()
		rows = frappe.get_all("Comment", {"reference_name": self.request}, ["content", "subject"])
		self.assertGreaterEqual(len(rows), 2)  # the Info comment and the Attachment comments of the files
		for row in rows:
			self.assertEqual(row.content, f"Content erased {self.request}")
			self.assertIn(row.subject, (None, "", f"Content erased {self.request}"))

	def test_queued_emails_about_the_request_are_deleted(self):
		self.close()
		self.assertFalse(frappe.db.exists("Email Queue", self.queued.name))
		self.assertEqual(frappe.db.count("Email Queue Recipient", {"parent": self.queued.name}), 0)

	def test_a_request_with_no_files_and_no_emails_queues_nothing_for_after_the_commit(self):
		# Emails need a search purge too (fix round 1), so the premise now is: nothing attached at all.
		frappe.db.delete("File", {"attached_to_name": ["in", [self.request, self.mail]]})
		frappe.db.delete("Communication", {"name": ["in", [self.mail, self.sent]]})
		self.close()
		self.assertEqual(self.byte_deletions_queued(), 0)
		self.assertFalse(self.stored("pending_file_deletions").pending_file_deletions)
