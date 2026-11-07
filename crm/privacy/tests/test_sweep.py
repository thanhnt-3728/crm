import json
import os
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils.file_manager import save_file

from crm.fcrm.doctype.crm_deal.crm_deal import remove_contact
from crm.privacy import erasure
from crm.privacy.erasure import run_erasure
from crm.privacy.reminders import notify
from crm.privacy.sweep import sweep_activities
from crm.privacy.tests.factories import (
	MARISOL_EMAIL,
	make_call_log,
	make_communication,
	make_compliance_user,
	make_marisol,
	make_note,
	make_request,
)

EMAIL = "marisol@sierrafoothills.example"
RECORDINGS = "Delete recordings at provider (Twilio)"


def _raw(values: dict) -> "frappe.model.document.Document":
	"""Insert a row and its child rows without running controllers (no account or disk needed)."""
	doc = frappe.get_doc(values)
	doc.name = doc.name or frappe.generate_hash(length=10)
	doc.set_user_and_timestamp()
	doc.db_insert()
	for child in doc.get_all_children():
		child.name = frappe.generate_hash(length=10)
		child.parent, child.parenttype = doc.name, doc.doctype
		child.db_insert()
	return doc


class TestSweep(IntegrationTestCase):
	def setUp(self):
		# Error Log lives in the SQLite log database, outside the test transaction.
		log_error = patch("frappe.log_error")
		log_error.start()
		self.addCleanup(log_error.stop)
		self.paths: list[str] = []
		self.m = make_marisol()
		self.officer = make_compliance_user()
		self.name = make_request(
			identifiers=[{"kind": "Email", "value": EMAIL}, {"kind": "Phone", "value": "5305550142"}],
			matches=[
				{"reference_doctype": d, "reference_name": n, "confirmed": 1}
				for d, n in [
					("CRM Lead", self.m.lead),
					("Contact", self.m.contact),
					("CRM Deal", self.m.won_deal),
					("CRM Deal", self.m.open_deal),
				]
			],
		).name
		remove_contact(self.m.open_deal, self.m.contact)
		frappe.db.set_value("CRM Erasure Request", self.name, "status", "Awaiting Sign-off")
		self.P = f"Erased person {self.name}"
		self.C = f"Content erased {self.name}"

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		# The rollback leaves files written to disk behind.
		for path in self.paths:
			if os.path.exists(path):
				os.remove(path)

	def _save_file(self, name: str, content: bytes, doctype: str, docname: str):
		f = save_file(name, content, doctype, docname)
		self.paths.append(f.get_full_path())
		return f

	# From the brief

	def test_email_wiped_everywhere_colleague_kept(self):
		c = make_communication(
			sender="tyler@northpine.example",
			recipients='"Marisol Vega" <marisol@sierrafoothills.example>, dana@northpine.example',
			subject="Quote",
			content="Hi Marisol, call 530-555-0142",
		)
		run_erasure(self.name, self.officer)
		row = frappe.db.get_value("Communication", c, ["subject", "content", "recipients", "sender"], as_dict=True)
		self.assertEqual(row.subject, self.C)
		self.assertEqual(row.content, self.C)
		self.assertEqual(row.recipients, f"Erased person {self.name}, dana@northpine.example")
		self.assertEqual(row.sender, "tyler@northpine.example")

	def test_call_log_number_and_recording(self):
		cl = make_call_log(**{"from": "(530) 555-0142", "to": "+15550001111", "recording_url": "https://x/r.mp3"})
		run_erasure(self.name, self.officer)
		row = frappe.db.get_value("CRM Call Log", cl, ["from", "to", "recording_url"], as_dict=True)
		self.assertEqual((row["from"], row.to, row.recording_url), (self.P, "+15550001111", None))
		items = frappe.get_all("CRM Erasure Checklist Item", {"parent": self.name}, pluck="description")
		self.assertEqual(items, [RECORDINGS])

	def test_task_text_wiped_status_kept(self):
		t = frappe.get_doc(
			{
				"doctype": "CRM Task",
				"title": "Call Marisol",
				"status": "Todo",
				"reference_doctype": "CRM Lead",
				"reference_docname": self.m.lead,
			}
		).insert()
		run_erasure(self.name, self.officer)
		self.assertEqual(frappe.db.get_value("CRM Task", t.name, ["title", "status"]), (self.C, "Todo"))

	def test_shared_file_content_survives(self):
		f1 = self._save_file("proposal.txt", b"x", "CRM Lead", self.m.lead)
		f2 = frappe.get_doc(
			{
				"doctype": "File",
				"file_url": f1.file_url,
				"attached_to_doctype": "CRM Organization",
				"attached_to_name": self.m.org,
			}
		).insert()
		path = f1.get_full_path()
		run_erasure(self.name, self.officer)
		frappe.db.after_commit.run()
		self.assertFalse(frappe.db.exists("File", f1.name))
		self.assertTrue(frappe.db.exists("File", f2.name))
		self.assertTrue(os.path.exists(path))
		self.assertTrue(
			frappe.db.exists("Comment", {"reference_name": self.m.lead, "content": f"File erased {self.name}"})
		)

	def test_unshared_file_removed_from_disk_only_after_commit(self):
		f = self._save_file("id.txt", b"y", "CRM Lead", self.m.lead)
		path = f.get_full_path()
		run_erasure(self.name, self.officer)
		self.assertTrue(os.path.exists(path))  # nothing leaves disk before commit
		frappe.db.after_commit.run()
		self.assertFalse(os.path.exists(path))

	# Beyond the brief

	def test_received_email_sender_name_phone_and_plain_text(self):
		c = make_communication(
			sender=f"Marisol Vega <{MARISOL_EMAIL}>",
			sender_full_name="Marisol Vega",
			recipients="tyler@northpine.example",
			cc="dana@northpine.example",
			phone_no="+1 530 555 0142",
			text_content="Hi, this is Marisol",
			sent_or_received="Received",
		)
		other = make_communication(
			sender="dana@northpine.example", sender_full_name="Dana", recipients="tyler@northpine.example"
		)
		run_erasure(self.name, self.officer)
		row = frappe.db.get_value(
			"Communication",
			c,
			["sender", "sender_full_name", "recipients", "cc", "phone_no", "text_content"],
			as_dict=True,
		)
		self.assertEqual(
			(row.sender, row.sender_full_name, row.recipients, row.cc, row.phone_no, row.text_content),
			(self.P, self.P, "tyler@northpine.example", "dana@northpine.example", self.P, self.C),
		)
		row = frappe.db.get_value("Communication", other, ["subject", "sender_full_name"], as_dict=True)
		self.assertEqual((row.subject, row.sender_full_name), ("Hello", "Dana"))

	def test_comment_wiped_and_comment_cache_reset(self):
		comment = frappe.get_doc(
			{
				"doctype": "Comment",
				"comment_type": "Comment",
				"reference_doctype": "CRM Lead",
				"reference_name": self.m.lead,
				"content": "Marisol prefers mornings",
			}
		).insert(ignore_permissions=True)
		self.assertIn(comment.name, frappe.db.get_value("CRM Lead", self.m.lead, "_comments"))
		run_erasure(self.name, self.officer)
		self.assertEqual(frappe.db.get_value("Comment", comment.name, "content"), self.C)
		self.assertEqual(frappe.db.get_value("CRM Lead", self.m.lead, "_comments"), "[]")

	def test_call_log_note_wiped_note_on_removed_deal_kept(self):
		linked = make_note(("CRM Deal", self.m.open_deal), title="Call with Marisol", content="She called")
		make_call_log(**{"from": "+15305550142", "note": linked})
		kept = make_note(("CRM Deal", self.m.open_deal), title="Deal note", content="Pricing")
		mine = make_note(("CRM Lead", self.m.lead), title="Lead note", content="About Marisol")
		run_erasure(self.name, self.officer)
		for note in (linked, mine):
			self.assertEqual(frappe.db.get_value("FCRM Note", note, ["title", "content"]), (self.C, self.C))
		self.assertEqual(frappe.db.get_value("FCRM Note", kept, ["title", "content"]), ("Deal note", "Pricing"))

	def test_recordings_item_added_once(self):
		request = frappe.get_doc("CRM Erasure Request", self.name)
		request.append("checklist", {"description": RECORDINGS})
		request.flags.privacy_system_write = True
		request.save(ignore_permissions=True)
		make_call_log(**{"from": "+15305550142", "recording_url": "https://x/r.mp3"})
		run_erasure(self.name, self.officer)
		items = frappe.get_all("CRM Erasure Checklist Item", {"parent": self.name}, pluck="description")
		self.assertEqual(items, [RECORDINGS])

	def test_no_recordings_no_item(self):
		make_call_log(**{"from": "+15305550142"})
		run_erasure(self.name, self.officer)
		self.assertEqual(frappe.db.count("CRM Erasure Checklist Item", {"parent": self.name}), 0)

	def test_hold_notification_and_its_email_become_content_placeholder(self):
		# What crm.privacy.hold sends to a deal owner: it names the contact.
		notify(
			[self.officer],
			f"Erasure request {self.name} is on hold: contact Marisol Vega on deal {self.m.open_deal} asked to be erased.",
			self.name,
			reference_doctype="CRM Deal",
			reference_name=self.m.open_deal,
		)
		notification = frappe.db.get_value(
			"CRM Notification", {"notification_type_doc": self.name, "to_user": self.officer}, "name"
		)
		queued = frappe.get_all(
			"Email Queue", {"reference_doctype": "CRM Erasure Request", "reference_name": self.name}, pluck="name"
		)
		self.assertTrue(notification)
		self.assertTrue(queued)
		self.assertEqual(
			set(frappe.get_all("Email Queue", {"name": ["in", queued]}, pluck="status")), {"Not Sent"}
		)
		run_erasure(self.name, self.officer)
		row = frappe.db.get_value("CRM Notification", notification, ["message", "notification_text"], as_dict=True)
		self.assertEqual((row.message, row.notification_text), (self.C, self.C))
		# Not sent yet: deleted with its recipients rather than sent as a bare placeholder.
		self.assertFalse(frappe.db.exists("Email Queue", {"name": ["in", queued]}))
		self.assertFalse(frappe.db.exists("Email Queue Recipient", {"parent": ["in", queued]}))

	def test_pending_queued_email_deleted_sent_one_wiped(self):
		def queue(status: str, recipient_status: str):
			return _raw(
				{
					"doctype": "Email Queue",
					"sender": "tyler@northpine.example",
					"message": "Subject: Your quote\n\nHi Marisol",
					"status": status,
					"reference_doctype": "CRM Lead",
					"reference_name": self.m.lead,
					"recipients": [
						{"recipient": MARISOL_EMAIL, "status": recipient_status},
						{"recipient": "dana@northpine.example", "status": recipient_status},
					],
				}
			).name

		pending, partly, sent = queue("Not Sent", "Not Sent"), queue("Partially Sent", "Sent"), queue("Sent", "Sent")
		other = queue("Not Sent", "Not Sent")
		frappe.db.set_value("Email Queue", other, {"reference_doctype": "CRM Organization", "reference_name": self.m.org})
		frappe.db.set_value("Email Queue", other, "message", "Subject: Org\n\nHi Dana")
		frappe.db.delete("Email Queue Recipient", {"parent": other, "recipient": MARISOL_EMAIL})
		run_erasure(self.name, self.officer)
		for name in (pending, partly):
			self.assertFalse(frappe.db.exists("Email Queue", name))
			self.assertFalse(frappe.db.exists("Email Queue Recipient", {"parent": name}))
		self.assertEqual(frappe.db.get_value("Email Queue", sent, ["message", "status"]), (self.C, "Sent"))
		recipients = frappe.get_all(
			"Email Queue Recipient", {"parent": sent}, pluck="recipient", parent_doctype="Email Queue"
		)
		self.assertEqual(sorted(recipients), sorted([self.P, "dana@northpine.example"]))
		self.assertEqual(frappe.db.get_value("Email Queue", other, "message"), "Subject: Org\n\nHi Dana")

	def test_queued_email_on_old_contact_name_follows_rename(self):
		sent = _raw(
			{
				"doctype": "Email Queue",
				"sender": "tyler@northpine.example",
				"message": "Subject: Hello\n\nHi",
				"status": "Sent",
				"reference_doctype": "Contact",
				"reference_name": self.m.contact,
			}
		).name
		run_erasure(self.name, self.officer)
		self.assertEqual(
			frappe.db.get_value("Email Queue", sent, ["reference_name", "message"]), (self.P, self.C)
		)

	def test_wiped_email_leaves_global_search_after_commit(self):
		from frappe.utils.global_search import sync_value

		c = make_communication(
			sender=MARISOL_EMAIL, recipients="tyler@northpine.example", subject="Quote", sent_or_received="Received"
		)
		values = {"doctype": "Communication", "name": c, "published": 0, "title": "Quote", "route": ""}
		# __global_search is MyISAM, outside the test transaction: clean up by hand.
		sync_value({**values, "content": f"Subject: Quote ||| Sender: {MARISOL_EMAIL}"})
		try:
			run_erasure(self.name, self.officer)
			self.assertTrue(frappe.db.exists("__global_search", {"doctype": "Communication", "name": c}))
			frappe.db.after_commit.run()
			self.assertFalse(frappe.db.exists("__global_search", {"doctype": "Communication", "name": c}))
			self.assertFalse(frappe.db.exists("__global_search", {"content": ["like", "%sierrafoothills%"]}))
		finally:
			frappe.db.delete("__global_search", {"doctype": "Communication", "name": c})

	def test_whatsapp_logs_with_her_number_or_email(self):
		if not frappe.db.table_exists("WA Log"):
			self.skipTest("whatsapp is not installed")
		payload = {"entry": [{"changes": [{"value": {"contacts": [{"wa_id": "15305550142", "profile": {"name": "Marisol"}}]}}]}]}
		hers = _raw(
			{
				"doctype": "WA Log",
				"level": "Info",
				"event_type": "Webhook",
				"message": "Incoming text message from 15305550142 (Marisol)",
				"request_data": json.dumps(payload),
			}
		)
		by_email = _raw(
			{"doctype": "WA Log", "level": "Info", "event_type": "API", "message": f"Sent to {MARISOL_EMAIL}"}
		)
		other_payload = json.dumps({"contacts": [{"wa_id": "15550001111", "profile": {"name": "Dana"}}]})
		other = _raw(
			{
				"doctype": "WA Log",
				"level": "Info",
				"event_type": "Webhook",
				"message": "Incoming text message from 15550001111 (Dana)",
				"request_data": other_payload,
			}
		)
		run_erasure(self.name, self.officer)
		self.assertEqual(frappe.db.get_value("WA Log", hers.name, ["request_data", "message"]), ("{}", self.C))
		self.assertEqual(frappe.db.get_value("WA Log", by_email.name, "message"), self.C)
		self.assertEqual(
			frappe.db.get_value("WA Log", other.name, ["request_data", "message"]),
			(other_payload, "Incoming text message from 15550001111 (Dana)"),
		)

	def test_side_tables(self):
		# CRM Notification about something else that quotes her email: only the address goes.
		elsewhere = frappe.get_doc(
			{
				"doctype": "CRM Notification",
				"type": "Mention",
				"from_user": "Administrator",
				"to_user": self.officer,
				"message": f"Ask {MARISOL_EMAIL} about the order",
				"notification_text": "Order question",
				"reference_doctype": "CRM Organization",
				"reference_name": self.m.org,
			}
		).insert(ignore_permissions=True)
		todo_mine = frappe.get_doc(
			{"doctype": "ToDo", "description": "Call Marisol", "reference_type": "CRM Lead", "reference_name": self.m.lead}
		).insert(ignore_permissions=True)
		todo_other = frappe.get_doc(
			{"doctype": "ToDo", "description": "Ring 530-555-0142 back about the org"}
		).insert(ignore_permissions=True)
		log = _raw(
			{
				"doctype": "Notification Log",
				"for_user": self.officer,
				"type": "Alert",
				"subject": "Marisol Vega replied",
				"email_content": "Marisol Vega wrote back",
				"document_type": "CRM Lead",
				"document_name": self.m.lead,
			}
		)
		event = _raw(
			{
				"doctype": "Event",
				"subject": "Demo",
				"starts_on": "2026-11-10 10:00:00",
				"event_participants": [
					{"reference_doctype": "Contact", "reference_docname": self.m.contact, "email": MARISOL_EMAIL},
					{"reference_doctype": "Contact", "reference_docname": self.m.contact, "email": "dana@northpine.example"},
				],
			}
		)
		sync_hers = _raw(
			{
				"doctype": "Failed Lead Sync Log",
				"type": "Failure",
				"lead_data": json.dumps({"email": MARISOL_EMAIL, "phone": "+15305550142"}),
				"traceback": "Traceback: duplicate lead",
			}
		)
		sync_other = _raw(
			{
				"doctype": "Failed Lead Sync Log",
				"type": "Failure",
				"lead_data": json.dumps({"email": "someone@else.example", "phone": "+15550001111"}),
				"traceback": "Traceback: other",
			}
		)
		run = _raw(
			{
				"doctype": "CRM Enrichment Run",
				"reference_doctype": "CRM Lead",
				"reference_name": self.m.lead,
				"status": "Completed",
				"raw_json": json.dumps({"email": MARISOL_EMAIL}),
				"notes": "Found Marisol on LinkedIn",
				"social_profiles": "https://linkedin.example/marisol",
				"changes": [
					{"fieldname": "email", "old_value": "", "new_value": MARISOL_EMAIL},
					{"fieldname": "status", "old_value": "New", "new_value": "Contacted"},
				],
			}
		)
		queue = _raw(
			{
				"doctype": "Email Queue",
				"sender": "tyler@northpine.example",
				"message": "Subject: Hello\n\nHi there",
				"status": "Sent",
				"recipients": [{"recipient": MARISOL_EMAIL}, {"recipient": "dana@northpine.example"}],
			}
		)

		run_erasure(self.name, self.officer)

		row = frappe.db.get_value("CRM Notification", elsewhere.name, ["message", "notification_text"], as_dict=True)
		self.assertEqual((row.message, row.notification_text), (f"Ask {self.P} about the order", "Order question"))
		self.assertEqual(frappe.db.get_value("ToDo", todo_mine.name, "description"), self.C)
		self.assertEqual(
			frappe.db.get_value("ToDo", todo_other.name, "description"), f"Ring {self.P} back about the org"
		)
		self.assertEqual(
			frappe.db.get_value("Notification Log", log.name, ["subject", "email_content"]), (self.C, self.C)
		)
		emails = frappe.get_all(
			"Event Participants", {"parent": event.name}, pluck="email", order_by="email asc", parent_doctype="Event"
		)
		self.assertEqual(sorted(emails), sorted([self.P, "dana@northpine.example"]))
		self.assertEqual(
			frappe.db.get_value("Failed Lead Sync Log", sync_hers.name, ["lead_data", "traceback"]), (self.C, self.C)
		)
		self.assertEqual(
			frappe.db.get_value("Failed Lead Sync Log", sync_other.name, "traceback"), "Traceback: other"
		)
		row = frappe.db.get_value("CRM Enrichment Run", run.name, ["raw_json", "notes", "social_profiles"], as_dict=True)
		self.assertEqual((row.raw_json, row.notes, row.social_profiles), ("{}", self.C, ""))
		changes = {
			c.fieldname: (c.old_value, c.new_value)
			for c in frappe.get_all(
				"CRM Enrichment Run Change",
				{"parent": run.name},
				["fieldname", "old_value", "new_value"],
				parent_doctype="CRM Enrichment Run",
			)
		}
		self.assertEqual(changes, {"email": (self.C, self.C), "status": ("New", "Contacted")})
		self.assertEqual(frappe.db.get_value("Email Queue", queue.name, "message"), self.C)
		recipients = frappe.get_all(
			"Email Queue Recipient", {"parent": queue.name}, pluck="recipient", parent_doctype="Email Queue"
		)
		self.assertEqual(sorted(recipients), sorted([self.P, "dana@northpine.example"]))

	def test_whatsapp_profile_and_messages(self):
		if not frappe.db.table_exists("WA Message"):
			self.skipTest("whatsapp is not installed")
		hers = _raw(
			{"doctype": "WA Profile", "phone_number": "+15305550142", "profile_name": "Marisol", "wa_id": "15305550142"}
		)
		other = _raw({"doctype": "WA Profile", "phone_number": "+15550001111", "profile_name": "Dana"})
		to_her = _raw(
			{
				"doctype": "WA Message",
				"to": hers.name,
				"direction": "Incoming",
				"message": "Hi it's Marisol",
				"media_url": "Marisol_Vega_ID.pdf",
			}
		)
		on_lead = _raw(
			{
				"doctype": "WA Message",
				"to": other.name,
				"direction": "Outgoing",
				"message": "Hello",
				"reference_doctype": "CRM Lead",
				"reference_docname": self.m.lead,
			}
		)
		unrelated = _raw({"doctype": "WA Message", "to": other.name, "direction": "Outgoing", "message": "Hi Dana"})
		run_erasure(self.name, self.officer)
		self.assertEqual(
			frappe.db.get_value("WA Profile", hers.name, ["phone_number", "profile_name", "wa_id"]), (self.P,) * 3
		)
		self.assertEqual(frappe.db.get_value("WA Profile", other.name, "phone_number"), "+15550001111")
		self.assertEqual(frappe.db.get_value("WA Message", to_her.name, ["message", "media_url"]), (self.C, ""))
		self.assertEqual(frappe.db.get_value("WA Message", on_lead.name, "message"), self.C)
		self.assertEqual(frappe.db.get_value("WA Message", unrelated.name, "message"), "Hi Dana")

	def test_touched_activities_reindexed_after_commit(self):
		c = make_communication(sender="tyler@northpine.example", recipients=MARISOL_EMAIL)
		note = make_note(("CRM Lead", self.m.lead))
		comment = frappe.get_doc(
			{
				"doctype": "Comment",
				"comment_type": "Comment",
				"reference_doctype": "CRM Lead",
				"reference_name": self.m.lead,
				"content": "x",
			}
		).insert(ignore_permissions=True)
		run_erasure(self.name, self.officer)
		with (
			patch("crm.search_sqlite.CRMSearch.is_search_enabled", return_value=True),
			patch("crm.search_sqlite.CRMSearch.index_exists", return_value=True),
			patch("crm.search_sqlite.CRMSearch.index_doc") as index_doc,
		):
			frappe.db.after_commit.run()
		indexed = {call.args for call in index_doc.call_args_list}
		for item in (("Communication", c), ("FCRM Note", note), ("Comment", comment.name)):
			self.assertIn(item, indexed)

	def test_failed_sweep_rolls_back_and_keeps_files(self):
		f = self._save_file("kept.txt", b"z", "CRM Lead", self.m.lead)
		c = make_communication(sender="tyler@northpine.example", recipients=MARISOL_EMAIL, subject="Quote")

		def boom(*a):
			raise RuntimeError("x")

		with patch.object(erasure, "STEPS", [erasure.erase_records, sweep_activities, boom]):
			run_erasure(self.name, self.officer)
		frappe.db.after_commit.run()
		self.assertEqual(frappe.db.get_value("CRM Erasure Request", self.name, "erasure_status"), "Failed")
		self.assertTrue(frappe.db.exists("File", f.name))
		self.assertTrue(os.path.exists(f.get_full_path()))
		self.assertEqual(frappe.db.get_value("Communication", c, "subject"), "Quote")

	def test_sweep_is_in_the_erasure_steps(self):
		self.assertEqual(erasure.STEPS[:2], [erasure.erase_records, sweep_activities])
