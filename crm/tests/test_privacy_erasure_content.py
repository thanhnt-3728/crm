# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import json
import os
from contextlib import contextmanager
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_months, getdate, today

from crm.fcrm.doctype.crm_erasure_request.test_crm_erasure_request import make_request, make_user
from crm.privacy import system_write
from crm.privacy.erasure import CHECKLIST_TWILIO, placeholder_content, placeholder_person, run_erasure
from crm.privacy.erasure_content import replace_addresses, replace_person_text, split_person_values
from crm.privacy.identifiers import is_do_not_contact
from crm.privacy.preview import TWILIO_CHECKLIST_ITEM
from crm.privacy.setup import ensure_privacy_setup
from crm.tests import test_privacy_erasure_records as records
from crm.tests.test_privacy_matching import OWNER, ensure_deal_status, make_person
from crm.tests.test_privacy_preview import make_call_log, make_communication, make_note

SAVEPOINT = "test_privacy_erasure_content"
JOB_SAVEPOINT = "test_privacy_erasure_job"
EMAIL = "marisol@x.net"
PHONE = "+19165550100"
BOB_EMAIL = "bob@x.net"
BOB_PHONE = "+14155550123"
CARL_EMAIL = "carl@x.net"


@contextmanager
def job_transaction():
	"""Run the erasure job as if in a transaction of its own, inside the test's: its commit
	runs the after-commit work (file removal, re-indexing) without committing the test's
	data, and its rollback undoes only what the job did, dropping that work as a real
	rollback would."""
	db = frappe.local.db
	rollback = db.rollback

	def job_commit(*args, **kwargs):
		db.after_commit.run()

	def job_rollback(*args, **kwargs):
		rollback(save_point=JOB_SAVEPOINT)
		db.after_commit.reset()

	db.savepoint(JOB_SAVEPOINT)
	with patch.object(db, "commit", job_commit), patch.object(db, "rollback", job_rollback):
		yield


def make_file(name, content, **values):
	file = frappe.get_doc(
		{"doctype": "File", "file_name": name, "content": content, "is_private": 0, **values}
	).insert(ignore_permissions=True)
	return file, file.get_full_path()


class TestPrivacyErasureContent(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_privacy_setup()
		make_user(OWNER, ["Sales User"])

	def setUp(self):
		frappe.db.savepoint(SAVEPOINT)
		# Phone numbers below are typed without a country code, so the site region must be US.
		frappe.db.set_single_value("System Settings", "country", "United States")
		frappe.db.set_single_value("CRM Privacy Settings", "contract_retention_months", 0)
		self.build_person()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.flags.privacy_system_write = False
		frappe.flags.in_erasure_job = False
		frappe.db.rollback(save_point=SAVEPOINT)
		frappe.local.db.after_commit.reset()

	def build_person(self):
		"""Marisol: a lead, a contact and a Won deal she is still on, plus Bob's open deal she
		was taken off while the request was On Hold. Carl's deal has nothing to do with her."""
		self.lead, self.contact, self.own_deal = make_person(EMAIL, PHONE, status="Won")
		self.bob = records.make_contact("Bob", BOB_EMAIL, BOB_PHONE)

		removed = frappe.get_doc(
			{
				"doctype": "CRM Deal",
				"deal_owner": OWNER,
				"organization": "Removed Deal Org",
				"status": ensure_deal_status("Matching Open", "Open"),
				"contacts": [
					{"contact": self.bob.name, "is_primary": 1},
					{"contact": self.contact.name, "is_primary": 0},
				],
			}
		)
		removed.flags.ignore_mandatory = True
		removed.flags.ignore_links = True
		removed.insert(ignore_permissions=True)
		# Version: her contacts row removed.
		removed.contacts = [row for row in removed.contacts if row.contact != self.contact.name]
		self.removed_deal = records.save_deal(removed)

		carl = records.make_contact("Carl", CARL_EMAIL, "+14155550199")
		carl_deal = frappe.get_doc(
			{
				"doctype": "CRM Deal",
				"deal_owner": OWNER,
				"organization": "Unrelated Org",
				"status": ensure_deal_status("Matching Won", "Won"),
				"contacts": [{"contact": carl.name, "is_primary": 1}],
			}
		)
		carl_deal.flags.ignore_mandatory = True
		carl_deal.flags.ignore_links = True
		self.carl_deal = carl_deal.insert(ignore_permissions=True)

		self.request = make_request(
			requester_names="Marisol Vega",
			identifiers=[{"kind": "Email", "value": EMAIL}, {"kind": "Phone", "value": "(916) 555-0100"}],
		)
		for doctype, name, removed_from in (
			("CRM Lead", self.lead.name, 0),
			("Contact", self.contact.name, 0),
			("CRM Deal", self.own_deal.name, 0),
			("CRM Deal", self.removed_deal.name, 1),
		):
			self.request.append(
				"matches",
				{
					"reference_doctype": doctype,
					"reference_name": name,
					"confirmed": 1,
					"source": "Identifier match",
					"removed_from_open_deal": removed_from,
				},
			)
		with system_write():
			self.request.save(ignore_permissions=True)

	def set_status(self, status):
		self.request.reload()
		self.request.status = status
		with system_write():
			self.request.save(ignore_permissions=True)

	def run_job(self):
		"""Approve (status Erasing, as the approve API leaves it), then run the job."""
		self.set_status("Erasing")
		with job_transaction():
			run_erasure(self.request.name)
		self.request.reload()

	@property
	def person(self):
		return placeholder_person(self.request.name)

	@property
	def content(self):
		return placeholder_content(self.request.name)

	# -- pure helpers --------------------------------------------------------------------

	def test_checklist_constant_is_the_preview_one(self):
		self.assertEqual(CHECKLIST_TWILIO, TWILIO_CHECKLIST_ITEM)
		self.assertEqual(CHECKLIST_TWILIO, "Delete recordings at provider (Twilio)")

	def test_replace_addresses_pure(self):
		her = {EMAIL, "marisol.vega@x.net"}
		self.assertEqual(
			replace_addresses('"Vega, Marisol" <Marisol.Vega@X.net>; "Bob B" <bob@x.net>', her, "P"),
			'P, "Bob B" <bob@x.net>',
		)
		self.assertEqual(
			replace_addresses("amarisol@x.net, bob@x.net", her, "P"), "amarisol@x.net, bob@x.net"
		)

	def test_replace_person_text_pure(self):
		phones = [("1", "9165550100")]
		self.assertEqual(
			replace_person_text(
				"Marisol: (916) 555-0100, MARISOL@x.net", {EMAIL}, phones, {"Marisol"}, "P", "C"
			),
			"P: P, P",
		)
		self.assertEqual(replace_person_text("ref 916x555x0100", {EMAIL}, phones, (), "P", "C"), "C")
		self.assertEqual(split_person_values({EMAIL, PHONE, "Marisol"}), ({EMAIL}, {PHONE}, {"Marisol"}))

	# -- emails --------------------------------------------------------------------------

	def test_mixed_email_keeps_other_recipient(self):
		c = make_communication(
			recipients='"Marisol Vega" <Marisol@X.net>, bob@x.net',
			content="Hi Marisol, call me at 916-555-0100",
		)
		self.run_job()
		c.reload()
		self.assertEqual(c.content, self.content)
		self.assertEqual(c.subject, self.content)
		self.assertIn("bob@x.net", c.recipients)
		self.assertIn(self.person, c.recipients)
		self.assertNotIn("marisol", c.recipients.lower())
		self.assertTrue(frappe.db.exists("Communication", c.name))

	def test_her_sent_email_sender_replaced(self):
		c = make_communication(
			sender="Marisol.Vega <MARISOL@x.net>", sender_full_name="Marisol Vega", recipients=BOB_EMAIL
		)
		self.run_job()
		c.reload()
		self.assertEqual((c.sender, c.sender_full_name), (self.person, self.person))
		self.assertEqual(c.recipients, BOB_EMAIL)

	def test_email_on_unrelated_deal_matching_address_wiped(self):
		c = make_communication(
			reference=("CRM Deal", self.carl_deal.name),
			sender=CARL_EMAIL,
			recipients=BOB_EMAIL,
			cc=f"Marisol <{EMAIL}>",
			subject="Quote for Carl",
			content="Numbers attached",
		)
		self.run_job()
		c.reload()
		self.assertEqual((c.subject, c.content), (self.content, self.content))
		self.assertEqual((c.sender, c.recipients, c.cc), (CARL_EMAIL, BOB_EMAIL, self.person))
		self.assertEqual(c.reference_name, self.carl_deal.name)
		# Carl's deal itself is untouched.
		self.assertEqual(
			frappe.db.get_value("CRM Deal", self.carl_deal.name, "organization"), "Unrelated Org"
		)

	# -- calls, notes, tasks, comments ---------------------------------------------------

	def test_call_with_recording_adds_twilio_item(self):
		note = make_note(title="Call with Marisol")
		call = make_call_log(
			"erasure-call-rec",
			reference=("CRM Lead", self.lead.name),
			note=note.name,
			recording_url="https://api.twilio.com/recordings/RE123",
			**{"from": "916.555.0100", "to": "+14155550000"},
		)
		self.run_job()
		values = frappe.db.get_value("CRM Call Log", call.name, ["from", "to", "recording_url"], as_dict=True)
		self.assertEqual(values["from"], self.person)
		self.assertEqual(values["to"], "+14155550000")
		self.assertFalse(values.recording_url)
		self.assertEqual(
			frappe.db.get_value("FCRM Note", note.name, ["title", "content"]), (self.content, self.content)
		)
		items = [row for row in self.request.checklist if row.description == CHECKLIST_TWILIO]
		self.assertEqual(len(items), 1)
		self.assertEqual((items[0].auto_added, items[0].done), (1, 0))

	def test_call_without_recording_adds_no_item(self):
		make_call_log("erasure-call-plain", **{"from": "(916) 555-0100"})
		self.run_job()
		self.assertFalse([row for row in self.request.checklist if row.description == CHECKLIST_TWILIO])

	def test_note_on_removed_from_open_deal_untouched(self):
		note = make_note("CRM Deal", self.removed_deal.name, title="Open deal note")
		task = frappe.get_doc(
			{
				"doctype": "CRM Task",
				"title": "Send Bob the quote",
				"reference_doctype": "CRM Deal",
				"reference_docname": self.removed_deal.name,
			}
		).insert(ignore_permissions=True)
		# A call with her number on that deal is still wiped.
		call = make_call_log(
			"erasure-call-removed",
			reference=("CRM Deal", self.removed_deal.name),
			**{"from": "+1 916 555 0100"},
		)
		self.run_job()
		self.assertEqual(
			frappe.db.get_value("FCRM Note", note.name, ["title", "content"]),
			("Open deal note", "Spoke about the contract"),
		)
		self.assertEqual(frappe.db.get_value("CRM Task", task.name, "title"), "Send Bob the quote")
		self.assertEqual(frappe.db.get_value("CRM Call Log", call.name, "from"), self.person)

	def test_notes_tasks_comments_get_placeholder_and_task_keeps_state(self):
		note = make_note("CRM Deal", self.own_deal.name, title="Marisol's preferences")
		task = frappe.get_doc(
			{
				"doctype": "CRM Task",
				"title": "Call Marisol back",
				"description": "She asked about pricing",
				"status": "Todo",
				"priority": "High",
				"due_date": "2026-12-01 10:00:00",
				"assigned_to": "Administrator",
				"reference_doctype": "CRM Lead",
				"reference_docname": self.lead.name,
			}
		).insert(ignore_permissions=True)
		comment = frappe.get_doc(
			{
				"doctype": "Comment",
				"comment_type": "Comment",
				"reference_doctype": "CRM Lead",
				"reference_name": self.lead.name,
				"content": "Marisol prefers Tuesdays",
			}
		).insert(ignore_permissions=True)

		self.run_job()

		self.assertEqual(
			frappe.db.get_value("FCRM Note", note.name, ["title", "content"]), (self.content, self.content)
		)
		values = frappe.db.get_value(
			"CRM Task",
			task.name,
			["title", "description", "status", "priority", "assigned_to", "due_date"],
			as_dict=True,
		)
		self.assertEqual((values.title, values.description), (self.content, self.content))
		self.assertEqual(
			(values.status, values.priority, values.assigned_to), ("Todo", "High", "Administrator")
		)
		self.assertEqual(str(values.due_date), "2026-12-01 10:00:00")
		self.assertEqual(frappe.db.get_value("Comment", comment.name, "content"), self.content)
		# The lead's cached latest comments do not keep the text either.
		self.assertNotIn("Tuesdays", frappe.db.get_value("CRM Lead", self.lead.name, "_comments") or "")

	# -- files ---------------------------------------------------------------------------

	def test_files_deleted(self):
		on_lead, lead_path = make_file(
			"erasure-proposal-marisol.txt",
			"Proposal for Marisol",
			attached_to_doctype="CRM Lead",
			attached_to_name=self.lead.name,
		)
		self.addCleanup(lambda: os.path.exists(lead_path) and os.remove(lead_path))
		email = make_communication(reference=("CRM Lead", self.lead.name))
		on_email, email_path = make_file(
			"erasure-attachment.txt",
			"Signed form",
			attached_to_doctype="Communication",
			attached_to_name=email.name,
		)
		self.addCleanup(lambda: os.path.exists(email_path) and os.remove(email_path))
		bobs, bobs_path = make_file(
			"erasure-bob.txt", "Bob's file", attached_to_doctype="Contact", attached_to_name=self.bob.name
		)
		self.addCleanup(lambda: os.path.exists(bobs_path) and os.remove(bobs_path))
		self.assertTrue(os.path.exists(lead_path))

		self.run_job()

		for file, path in ((on_lead, lead_path), (on_email, email_path)):
			self.assertFalse(frappe.db.exists("File", file.name))
			self.assertFalse(
				frappe.db.exists("Deleted Document", {"deleted_doctype": "File", "deleted_name": file.name})
			)
			self.assertFalse(os.path.exists(path))
		# Where the attachment was listed, the email's placeholder stands in.
		self.assertEqual(frappe.db.get_value("Communication", email.name, "content"), self.content)
		self.assertTrue(frappe.db.exists("File", bobs.name))
		self.assertTrue(os.path.exists(bobs_path))

	# -- identifiers, contracts, status --------------------------------------------------

	def test_do_not_contact_created(self):
		self.run_job()
		self.assertTrue(is_do_not_contact("Phone", "916.555.0100"))
		self.assertTrue(is_do_not_contact("Email", "MARISOL@x.net"))
		self.assertFalse(is_do_not_contact("Email", BOB_EMAIL))

	def test_retained_contract_created(self):
		frappe.db.set_single_value("CRM Privacy Settings", "contract_retention_months", 12)
		self.request.db_set(
			{"contract_references": "SO-1001\n\nSO-1002\n", "requester_names": "Marisol Vega\nM. Vega"}
		)
		self.run_job()
		rows = frappe.get_all(
			"CRM Retained Contract",
			filters={"request": self.request.name},
			fields=["person_name", "contract_reference", "delete_after"],
			order_by="contract_reference asc",
		)
		self.assertEqual([row.contract_reference for row in rows], ["SO-1001", "SO-1002"])
		self.assertEqual({row.person_name for row in rows}, {"Marisol Vega"})
		self.assertEqual({getdate(row.delete_after) for row in rows}, {getdate(add_months(today(), 12))})

	def test_retained_contract_without_retention_or_requester_name(self):
		self.request.db_set({"contract_references": "MSA-7", "requester_names": ""})
		self.run_job()
		row = frappe.get_all(
			"CRM Retained Contract",
			filters={"request": self.request.name},
			fields=["person_name", "delete_after"],
		)[0]
		self.assertIsNone(row.delete_after)
		# Read from her records before they were erased.
		self.assertEqual(row.person_name, "Marisol")

	def test_status_erased_and_dashboard_unchanged(self):
		before = records.snapshot_dashboard()
		self.run_job()
		self.assertEqual(self.request.status, "Erased")
		self.assertTrue(self.request.erased_on)
		self.assertFalse(self.request.erasure_error)
		self.assertEqual(before, records.snapshot_dashboard())
		self.assertFalse(frappe.flags.in_erasure_job)

	def test_runs_only_while_erasing(self):
		self.set_status("Awaiting Sign-off")
		with job_transaction():
			self.assertRaises(frappe.ValidationError, run_erasure, self.request.name)
		self.assertEqual(
			frappe.db.get_value("CRM Erasure Request", self.request.name, "status"), "Awaiting Sign-off"
		)
		self.assertEqual(frappe.db.get_value("CRM Lead", self.lead.name, "email"), EMAIL)

	def test_failure_rolls_back_and_returns_to_awaiting(self):
		file, path = make_file(
			"erasure-kept.txt",
			"Kept on failure",
			attached_to_doctype="CRM Lead",
			attached_to_name=self.lead.name,
		)
		self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
		self.set_status("Erasing")
		with job_transaction():
			with patch("crm.privacy.erasure.erase_content", side_effect=Exception("boom")):
				self.assertRaises(Exception, run_erasure, self.request.name)
		self.assertEqual(
			frappe.db.get_value("CRM Erasure Request", self.request.name, ["status", "erasure_error"]),
			("Awaiting Sign-off", "boom"),
		)
		self.assertEqual(frappe.db.get_value("CRM Lead", self.lead.name, "email"), EMAIL)
		self.assertTrue(frappe.db.exists("Contact", self.contact.name))
		self.assertFalse(is_do_not_contact("Email", EMAIL))
		self.assertTrue(frappe.db.exists("File", file.name))
		self.assertTrue(os.path.exists(path))
		self.assertFalse(frappe.flags.in_erasure_job)

	# -- other places --------------------------------------------------------------------

	def make_notification(self, reference, message, text=""):
		return frappe.get_doc(
			{
				"doctype": "CRM Notification",
				"type": "Mention",
				"from_user": "Administrator",
				"to_user": "Administrator",
				"reference_doctype": reference[0],
				"reference_name": reference[1],
				"message": message,
				"notification_text": text,
			}
		).insert(ignore_permissions=True)

	def test_notification_text_replaced(self):
		on_lead = self.make_notification(
			("CRM Lead", self.lead.name), "<b>Admin</b> mentioned you on Marisol Vega", "Call Marisol"
		)
		names_her = self.make_notification(
			("CRM Deal", self.carl_deal.name), "Forwarded from MARISOL@x.net to Carl", ""
		)
		unrelated = self.make_notification(
			("CRM Deal", self.carl_deal.name), "Marisol from accounting says hi"
		)
		self.run_job()
		self.assertEqual(
			frappe.db.get_value("CRM Notification", on_lead.name, ["message", "notification_text"]),
			(f"<b>Admin</b> mentioned you on {self.person}", f"Call {self.person}"),
		)
		self.assertEqual(
			frappe.db.get_value("CRM Notification", names_her.name, "message"),
			f"Forwarded from {self.person} to Carl",
		)
		self.assertEqual(
			frappe.db.get_value("CRM Notification", unrelated.name, "message"),
			"Marisol from accounting says hi",
		)

	def test_email_queue_to_her_deleted(self):
		def queue(recipient):
			return frappe.get_doc(
				{
					"doctype": "Email Queue",
					"sender": "crm@example.com",
					"message": "Hello",
					"recipients": [{"recipient": recipient}],
				}
			).insert(ignore_permissions=True)

		hers, bobs = queue("Marisol <Marisol@X.net>"), queue(BOB_EMAIL)
		self.run_job()
		self.assertFalse(frappe.db.exists("Email Queue", hers.name))
		self.assertFalse(frappe.db.exists("Deleted Document", {"deleted_name": hers.name}))
		self.assertTrue(frappe.db.exists("Email Queue", bobs.name))

	def test_event_participant_email_replaced(self):
		event = frappe.get_doc(
			{
				"doctype": "Event",
				"subject": "Demo",
				"starts_on": "2026-12-01 10:00:00",
				"event_type": "Private",
				"event_participants": [
					{
						"reference_doctype": "CRM Lead",
						"reference_docname": self.lead.name,
						"email": " Marisol@X.net",
					},
					{"reference_doctype": "Contact", "reference_docname": self.bob.name, "email": BOB_EMAIL},
				],
			}
		)
		event.flags.ignore_mandatory = True
		event.flags.ignore_links = True
		event.insert(ignore_permissions=True)
		self.run_job()
		emails = frappe.get_all(
			"Event Participants", filters={"parent": event.name}, pluck="email", parent_doctype="Event"
		)
		self.assertEqual(sorted(emails), sorted([self.person, BOB_EMAIL]))

	def test_failed_lead_sync_log_wiped(self):
		if not frappe.db.table_exists("Failed Lead Sync Log"):
			self.skipTest("lead syncing not installed")

		def log(data):
			doc = frappe.get_doc(
				{"doctype": "Failed Lead Sync Log", "type": "Failure", "lead_data": json.dumps(data)}
			)
			doc.flags.ignore_links = True
			return doc.insert(ignore_permissions=True)

		hers = log({"first_name": "M", "mobile_no": "(916) 555-0100"})
		bobs = log({"first_name": "Bob", "email": BOB_EMAIL})
		self.run_job()
		self.assertEqual(frappe.db.get_value("Failed Lead Sync Log", hers.name, "lead_data"), self.content)
		self.assertIn(BOB_EMAIL, frappe.db.get_value("Failed Lead Sync Log", bobs.name, "lead_data"))

	def test_enrichment_change_value_replaced(self):
		if not frappe.db.table_exists("CRM Enrichment Run Change"):
			self.skipTest("domain enrichment not installed")
		run = frappe.get_doc(
			{
				"doctype": "CRM Enrichment Run",
				"reference_doctype": "CRM Deal",
				"reference_name": self.carl_deal.name,
				"status": "Completed",
				"raw_json": json.dumps({"emails": [EMAIL, CARL_EMAIL]}),
				"changes": [
					{"fieldname": "email", "old_value": "", "new_value": "Marisol@X.net"},
					{"fieldname": "website", "old_value": "", "new_value": "https://x.net"},
				],
			}
		).insert(ignore_permissions=True)
		self.run_job()
		changes = {
			row.fieldname: row
			for row in frappe.get_all(
				"CRM Enrichment Run Change",
				filters={"parent": run.name},
				fields=["fieldname", "old_value", "new_value"],
				parent_doctype="CRM Enrichment Run",
			)
		}
		self.assertEqual(changes["email"].new_value, self.person)
		self.assertEqual(changes["website"].new_value, "https://x.net")
		raw = frappe.db.get_value("CRM Enrichment Run", run.name, "raw_json")
		self.assertNotIn(EMAIL, raw.lower())
		self.assertIn(CARL_EMAIL, raw)

	def test_whatsapp_messages_wiped_and_profile_deleted(self):
		if not (frappe.db.table_exists("WA Message") and frappe.db.table_exists("WA Profile")):
			self.skipTest("whatsapp not installed")

		def profile(phone):
			doc = frappe.get_doc(
				{"doctype": "WA Profile", "name": frappe.generate_hash(length=10), "phone_number": phone}
			)
			doc.db_insert()
			return doc.name

		def message(to, text, reference=None):
			doc = frappe.get_doc(
				{
					"doctype": "WA Message",
					"name": frappe.generate_hash(length=10),
					"to": to,
					"message": text,
					"reference_doctype": reference[0] if reference else None,
					"reference_docname": reference[1] if reference else None,
				}
			)
			doc.db_insert()
			return doc.name

		# Her profile's number is typed differently from the identifier.
		hers, bobs = profile("+1 916-555-0100"), profile(BOB_PHONE)
		on_lead = message(hers, "Hi, it's Marisol", ("CRM Lead", self.lead.name))
		elsewhere = message(hers, "Me again")
		bob_message = message(bobs, "Bob here", ("CRM Deal", self.carl_deal.name))

		self.run_job()

		for name in (on_lead, elsewhere):
			self.assertEqual(frappe.db.get_value("WA Message", name, ["message", "to"]), (self.content, None))
		self.assertFalse(frappe.db.exists("WA Profile", hers))
		self.assertTrue(frappe.db.exists("WA Profile", bobs))
		self.assertEqual(
			frappe.db.get_value("WA Message", bob_message, ["message", "to"]), ("Bob here", bobs)
		)

	# -- change history outside the erased records -----------------------------------------

	def versions_of(self, doctype, name):
		return frappe.get_all("Version", filters={"ref_doctype": doctype, "docname": name}, pluck="data")

	def test_removed_from_deal_history_scrubbed_bobs_kept(self):
		old_contact = self.contact.name
		history = self.versions_of("CRM Deal", self.removed_deal.name)
		# Guard: the removal is in the deal's history, naming her contact.
		self.assertTrue(any(f'"{old_contact}"' in data for data in history))
		self.run_job()
		history = " ".join(self.versions_of("CRM Deal", self.removed_deal.name))
		self.assertNotIn(f'"{old_contact}"', history)
		self.assertNotIn(EMAIL, history.lower())
		self.assertIn(self.person, history)

	def test_other_lead_history_naming_her_scrubbed(self):
		other = frappe.get_doc({"doctype": "CRM Lead", "first_name": "Rosa", "email": "rosa@x.net"})
		other.flags.ignore_mandatory = True
		other.insert(ignore_permissions=True)
		version = frappe.get_doc(
			{
				"doctype": "Version",
				"ref_doctype": "CRM Lead",
				"docname": other.name,
				"data": json.dumps(
					{"changed": [["email", "Marisol@X.net", "rosa@x.net"], ["status", "New", "Contacted"]]}
				),
			}
		).insert(ignore_permissions=True)
		self.run_job()
		data = json.loads(frappe.db.get_value("Version", version.name, "data"))
		self.assertEqual(
			data["changed"], [["email", self.person, "rosa@x.net"], ["status", "New", "Contacted"]]
		)
