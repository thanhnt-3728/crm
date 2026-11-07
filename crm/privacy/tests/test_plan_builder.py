# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""What the plan reaches in the Marisol scenario, kind by kind (phase 05 step 4; design 5.6, RT-4, RT-9, RT-14)."""

from itertools import chain

import frappe

from crm.privacy.erasure.plan_builder import build_plan
from crm.privacy.tests.erasure_fixture import ErasureTestCase


class PlanCase(ErasureTestCase):
	def setUp(self):
		super().setUp()
		self.plan = self.build()
		self.targets = self.plan.targets

	def build(self):
		return build_plan(frappe.get_doc("CRM Erasure Request", self.request))

	def assertTargets(self, kind, expected):
		self.assertEqual(sorted(self.targets[kind]), sorted(expected), kind)

	def references(self, doctype_field, name_field, doctype, names, **filters):
		return frappe.get_all(
			doctype,
			{
				doctype_field: ["in", ["CRM Lead", "Contact", "CRM Deal"]],
				name_field: ["in", names],
				**filters,
			},
			pluck="name",
		)


class TestRecords(PlanCase):
	def test_her_confirmed_records(self):
		self.assertTargets("leads", [self.p.lead])
		self.assertTargets("contacts", [self.p.contact])
		self.assertTargets("addresses", [self.p.address])

	def test_deals_by_how_she_is_on_them(self):
		self.assertTargets("deals_on", [self.p.won])
		self.assertTargets("deals_copy", [self.p.copy_deal])  # RT-14: listed, never confirmed
		self.assertTargets("deals_removed", [self.p.removed])

	def test_a_stranger_with_a_lookalike_email_and_phone_is_not_touched(self):
		everything = {name for names in self.targets.values() for name in names}
		self.assertNotIn(self.p.lookalike, everything)
		self.assertNotIn(self.p.colleague, everything)

	def test_the_identifiers_are_the_kept_ones_in_canonical_form(self):
		self.assertEqual(self.plan.identifiers.emails, {self.p.email, self.p.email2})
		self.assertEqual(self.plan.identifiers.phones, {self.p.phone, self.p.phone2})

	def test_her_values_and_the_personal_fields_are_carried_for_the_scrubbers(self):
		self.assertIn("Marisol", self.plan.her_values["first_name"])
		self.assertIn("Vega", self.plan.her_values["last_name"])
		self.assertIn("email", self.plan.personal_fields["CRM Lead"])
		self.assertIn("full_name", self.plan.personal_fields["CRM Contacts"])
		self.assertNotIn("personal_mobile", self.plan.personal_fields["CRM Lead"])


class TestActivities(PlanCase):
	def test_emails_by_link_or_by_whole_address(self):
		c = self.activity.communications
		# the invitation the event made (Communication Link to her contact) is hers too
		invitation = frappe.get_all("Communication", {"reference_doctype": "Event"}, pluck="name")
		self.assertEqual(len(invitation), 1)
		self.assertTargets(
			"communications",
			[c.mail_lead, c.mail_contact, c.mail_won, c.mail_removed, c.mail_loose, *invitation],
		)
		for kept in (c.mail_colleague, c.mail_lookalike, c.mail_shared, c.mail_copy_deal):
			self.assertNotIn(kept, self.targets["communications"])

	def test_calls_by_link_or_by_number_in_any_format(self):
		c = self.activity.calls
		self.assertTargets("call_logs", [c.call_recorded, c.call_by_number, c.call_removed])
		self.assertNotIn(c.call_lookalike, self.targets["call_logs"])
		self.assertTrue(self.plan.recordings)

	def test_notes_tasks_comments_and_todos_of_her_records_only(self):
		n, c = self.activity.notes, self.activity.calls
		self.assertTargets("notes", [n.note_lead, n.note_contact, n.note_won, c.call_note])
		self.assertTargets("tasks", [n.task_lead, n.task_contact, n.task_won])
		records = [self.p.lead, self.p.contact, self.p.won]
		# [I4] every Comment row on her records, whatever its type (Attachment rows carry file names)
		every = self.references("reference_doctype", "reference_name", "Comment", records)
		self.assertTargets("comments", every)
		self.assertTrue({n.comment_lead, n.comment_contact, n.comment_won} <= set(every))
		types = set(frappe.get_all("Comment", {"name": ["in", every]}, pluck="comment_type"))
		self.assertTrue(types - {"Comment"}, "the scenario has no system comment on her records")
		todos = self.references("reference_type", "reference_name", "ToDo", records)
		self.assertTargets("todos", todos)
		self.assertTrue({n.todo_lead, n.todo_contact, n.todo_won} <= set(todos))
		for kept in (n.note_removed, n.note_copy, n.task_removed, n.comment_removed, n.todo_removed):
			self.assertNotIn(
				kept,
				list(chain.from_iterable(self.targets[k] for k in ("notes", "tasks", "comments", "todos"))),
			)

	def test_an_address_shared_with_a_colleague_is_set_apart(self):
		shared = frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": "Sierra Office",
				"address_type": "Office",
				"address_line1": "9 Main St",
				"city": "Chico",
				"country": "United States",
				"links": [
					{"link_doctype": "Contact", "link_name": self.p.contact},
					{"link_doctype": "Contact", "link_name": self.p.colleague},
				],
			}
		).insert(ignore_permissions=True)
		before = self.plan.hash()
		plan = self.build()
		self.assertEqual(plan.targets["addresses"], [self.p.address])  # [I3]: not the shared one
		self.assertEqual(plan.shared_addresses, [shared.name])
		self.assertNotEqual(plan.hash(), before)  # the shared address is part of what was approved

	def test_files_on_her_records_and_her_emails(self):
		h = self.activity.history
		self.assertTargets(
			"files",
			[h.photo, h.file_lead, h.file_won, self.activity.communications.attachment, self.activity.extras.wa_file],
		)  # the last one is attached to her WhatsApp message (review M4)
		self.assertNotIn(h.file_removed, self.targets["files"])


class TestHistoryAndMisc(PlanCase):
	def test_versions_of_every_affected_record(self):
		docs = self.plan.docs()
		expected = frappe.get_all("Version", {"docname": ["in", [name for _dt, name in docs]]}, pluck="name")
		self.assertTargets("versions", expected)
		h = self.activity.history
		self.assertTrue({h.version_lead, h.version_contact, h.version_won_status} <= set(expected))

	def test_the_deleted_copy_of_her_second_lead(self):
		h = self.activity.history
		deleted = frappe.get_all("Deleted Document", {"deleted_name": h.deleted_lead}, pluck="name")
		self.assertEqual(len(deleted), 1)
		self.assertIn(deleted[0], self.targets["deleted_documents"])

	def test_rows_that_name_her_outside_the_crm_records(self):
		m = self.activity.misc
		self.assertIn(m.notification, self.targets["crm_notifications"])
		self.assertIn(m.email_queue, self.targets["email_queues"])
		self.assertTargets("wa_messages", [m.wa_message])
		self.assertEqual(len(self.targets["wa_profiles"]), 1)
		self.assertEqual(len(self.targets["event_participants"]), 1)
		self.assertTargets("failed_sync_logs", [m.failed_sync])

	def test_the_on_hold_notices_of_this_request_are_found_apart_from_her_rows(self):
		# the owner's notice, and the "ready for sign-off" notice to Compliance: both carry the request number
		notices = frappe.get_all(
			"CRM Notification",
			or_filters={"notification_type_doc": self.request, "reference_name": self.request},
			pluck="name",
		)
		queued = frappe.get_all("Email Queue", {"reference_name": self.request}, pluck="name")
		self.assertEqual(len(notices), 2)
		self.assertTargets("hold_notifications", notices)
		self.assertTargets("hold_emails", queued)
		self.assertFalse(set(notices) & set(self.targets["crm_notifications"]))
		self.assertNotIn(self.activity.misc.notification, self.targets["hold_notifications"])

	def test_a_data_import_for_leads_is_counted_and_the_custom_field_is_a_gap(self):
		self.assertGreaterEqual(self.plan.data_imports, 1)
		gaps = {(g["doctype"], g["fieldname"]) for g in self.plan.field_gaps}
		self.assertIn(("CRM Lead", "personal_mobile"), gaps)
		self.assertNotIn(("CRM Lead", "email"), gaps)
