# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Traces the review found still standing after an erasure (M4, L6) and the checklist for providers (L6)."""

import os

import frappe

from crm.privacy.tests.erasure_run_case import ExecutorCase


class LeftoverCase(ExecutorCase):
	def setUp(self):
		super().setUp()
		self.person = f"Erased person {self.request}"
		self.content = f"Content erased {self.request}"
		self.wa_path = frappe.get_doc("File", self.activity.extras.wa_file).get_full_path()


class TestQueuedMailAndWhatsApp(LeftoverCase):
	def test_cc_attachments_and_bounce_text_of_a_queued_mail_lose_her(self):
		self.approve_and_run()
		row = self.values(
			"Email Queue", self.activity.misc.email_queue, "show_as_cc", "attachments", "error", "message"
		)
		self.assertEqual(row.show_as_cc, f"{self.person}, {self.p.colleague_email}")
		self.assertFalse(row.attachments)
		self.assertNotIn(self.p.email, row.error or "")
		self.assertEqual(row.message, self.content)

	def test_whatsapp_media_parameters_and_attached_files_are_gone(self):
		self.approve_and_run()
		wa = self.values(
			"WA Message", self.activity.misc.wa_message, "attach", "media_url", "template_body_parameters"
		)
		self.assertFalse(any(wa.values()), wa)
		self.assertFalse(frappe.db.exists("File", self.activity.extras.wa_file))
		self.assertFalse(os.path.exists(self.wa_path))


class TestEventsAndDeletedNotes(LeftoverCase):
	def test_event_text_that_names_her_becomes_the_content_placeholder(self):
		self.approve_and_run()
		event = self.values("Event", self.activity.misc.event, "subject", "description")
		self.assertEqual([event.subject, event.description], [self.content, self.content])

	def test_a_note_deleted_earlier_is_found_by_the_record_it_was_about(self):
		self.approve_and_run()
		self.assertFalse(frappe.db.exists("Deleted Document", self.activity.extras.deleted_note))


class TestRouteHistoryAndSavedFilters(LeftoverCase):
	def routes(self):
		return frappe.get_all("Route History", pluck="route")

	def test_route_history_of_her_contact_and_address_is_deleted_and_others_stay(self):
		self.approve_and_run()
		routes = self.routes()
		self.assertFalse([r for r in routes if "Marisol" in r])
		self.assertIn("app/contact/Jon%20Park", routes)

	def test_saved_list_filters_lose_her_email_and_other_users_keep_theirs(self):
		self.approve_and_run()
		query = "select data from `__UserSettings` where `user` = %s and `doctype` = 'CRM Lead'"
		self.assertNotIn(self.p.email, frappe.db.sql(query, self.p.rep)[0][0])
		self.assertIn("New", frappe.db.sql(query, "Administrator")[0][0])


class TestProviderChecklist(LeftoverCase):
	def test_every_provider_with_recordings_gets_its_own_item(self):
		frappe.get_doc({"doctype": "CRM Call Log", "id": frappe.generate_hash(length=10), "from": self.p.phone,
			"to": "+15305559999", "type": "Incoming", "status": "Completed", "telephony_medium": "Exotel",
			"recording_url": "https://exotel.example/rec/1", "reference_doctype": "CRM Lead",
			"reference_docname": self.p.lead}).insert(ignore_permissions=True)  # fmt: skip
		self.approve_and_run()
		items = frappe.get_all("CRM Erasure Checklist Item", {"parent": self.request}, pluck="description")
		self.assertIn("Delete recordings at provider (Exotel)", items)
		self.assertIn("Delete recordings at provider (Twilio)", items)
