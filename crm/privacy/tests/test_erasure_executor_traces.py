# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The erasure job on files, change history and the rows outside the records (phase 05 steps 6-8, RT-8, RT-10)."""

import json
import os

import frappe

from crm.privacy.do_not_contact import is_blocked
from crm.privacy.tests.erasure_run_case import ExecutorCase


class TracesCase(ExecutorCase):
	def setUp(self):
		super().setUp()
		self.person = f"Erased person {self.request}"
		self.content = f"Content erased {self.request}"
		h = self.activity.history
		self.file_paths = {
			name: frappe.get_doc("File", name).get_full_path()
			for name in (
				h.photo,
				h.file_lead,
				h.file_won,
				h.file_removed,
				self.activity.communications.attachment,
			)
		}
		self.versions_before = {
			name: frappe.db.count("Version", {"docname": name})
			for name in (self.p.lead, self.p.won, self.p.removed, self.p.contact)
		}
		self.approve_and_run()

	def version_text(self, name):
		return frappe.db.get_value("Version", name, "data")


class TestFiles(TracesCase):
	def test_her_files_are_gone_from_disk_after_the_commit_and_the_others_stay(self):
		h = self.activity.history
		gone = (h.photo, h.file_lead, h.file_won, self.activity.communications.attachment)
		for name in gone:
			self.assertFalse(frappe.db.exists("File", name), name)
			self.assertFalse(os.path.exists(self.file_paths[name]), name)
		self.assertTrue(frappe.db.exists("File", h.file_removed))
		self.assertTrue(os.path.exists(self.file_paths[h.file_removed]))

	def test_the_pending_list_is_empty_once_the_bytes_are_deleted(self):
		self.assertFalse(self.stored("pending_file_deletions").pending_file_deletions)

	def test_a_placeholder_remains_where_a_file_was_listed(self):
		erased = frappe.get_all(
			"Comment", {"reference_doctype": "CRM Lead", "reference_name": self.p.lead,
			"content": f"File erased {self.request}", "comment_type": "Info"}, pluck="name"
		)  # fmt: skip
		self.assertEqual(len(erased), 1)


class TestHistory(TracesCase):
	def test_change_history_loses_her_values_and_keeps_the_rest(self):
		h = self.activity.history
		for name in (h.version_lead, h.version_contact):
			text = self.version_text(name)
			for secret in (self.p.email, "Practice manager", self.p.phone):
				self.assertNotIn(secret, text, name)
		status = json.loads(self.version_text(h.version_won_status))
		self.assertEqual(status["changed"], [["status", "Qualification", "Won"]])
		for deal in (self.p.won, self.p.removed):  # the removed-from deal's history too (plan call)
			for text in frappe.get_all("Version", {"docname": deal, "ref_doctype": "CRM Deal"}, pluck="data"):
				self.assertNotIn(self.p.email, text)
				self.assertNotIn(self.p.phone, text)

	def test_the_erasure_itself_writes_no_version(self):
		for name, before in self.versions_before.items():
			name = (
				self.person if name == self.p.contact else name
			)  # the contact was renamed, its rows followed
			self.assertEqual(frappe.db.count("Version", {"docname": name}), before, name)

	def test_the_deleted_copy_of_her_second_lead_is_gone(self):
		self.assertFalse(frappe.db.exists("Deleted Document", {"deleted_name": self.activity.history.deleted_lead,
			"data": ["like", f"%{self.p.email}%"]}))  # fmt: skip

	def test_the_comment_cache_of_her_records_is_reset(self):
		for doctype, name in (("CRM Lead", self.p.lead), ("CRM Deal", self.p.won), ("Contact", self.person)):
			self.assertEqual(frappe.db.get_value(doctype, name, "_comments"), "[]", name)


class TestRowsOutsideTheRecords(TracesCase):
	def test_notifications_and_queued_mail_that_name_her_are_replaced(self):
		m = self.activity.misc
		note = self.values("CRM Notification", m.notification, "message", "notification_text")
		self.assertEqual([note.message, note.notification_text], [self.content, self.content])
		self.assertEqual(self.values("Email Queue", m.email_queue, "message").message, self.content)
		recipients = frappe.get_all("Email Queue Recipient", {"parent": m.email_queue}, pluck="recipient")
		self.assertEqual(recipients, [self.person])

	def test_the_on_hold_notices_and_their_queued_mail_are_deleted(self):
		self.assertFalse(frappe.db.exists("CRM Notification", {"notification_type_doc": self.request}))
		self.assertFalse(frappe.db.exists("CRM Notification", {"reference_name": self.request}))
		self.assertFalse(frappe.db.exists("Email Queue", {"reference_name": self.request}))

	def test_whatsapp_event_and_sync_log_rows_are_cleaned(self):
		m = self.activity.misc
		message = self.values(
			"WA Message", m.wa_message, "message", "from", "reference_doctype", "reference_docname"
		)
		self.assertEqual((message.message, message["from"]), (self.content, self.person))
		self.assertFalse(message.reference_doctype or message.reference_docname)
		profile = frappe.get_all("WA Profile", {"phone_number": self.person}, pluck="name")
		self.assertEqual(len(profile), 1)
		self.assertEqual(
			frappe.db.count("Dynamic Link", {"parenttype": "WA Profile", "parent": profile[0]}), 0
		)
		participant = frappe.db.get_value("Event Participants", {"parent": m.event}, "email")
		self.assertFalse(participant)
		self.assertNotIn(
			self.p.email, frappe.db.get_value("Failed Lead Sync Log", m.failed_sync, "lead_data")
		)


class TestOutcome(TracesCase):
	def test_every_kept_identifier_is_blocked_and_the_shared_inbox_is_not(self):
		self.assertEqual(frappe.db.count("CRM Do Not Contact"), 4)
		for kind, value in (
			("email", self.p.email),
			("email", self.p.email2),
			("phone", self.p.phone),
			("phone", self.p.phone2),
		):
			self.assertTrue(is_blocked(kind, value), value)
		self.assertFalse(is_blocked("email", self.p.shared_email))

	def test_the_checklist_gets_the_provider_and_data_import_items(self):
		rows = frappe.get_all(
			"CRM Erasure Checklist Item", {"parent": self.request}, ["description", "auto_added", "done"]
		)
		texts = {r.description for r in rows}
		self.assertIn("Delete recordings at provider (Twilio)", texts)
		self.assertTrue(any(t.startswith("Check Data Import files for this person (") for t in texts))
		self.assertTrue(all(r.auto_added and not r.done for r in rows))
