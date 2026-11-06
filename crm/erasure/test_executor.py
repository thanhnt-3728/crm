# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase

from crm.erasure.erasure_test_fixture_execution import (
	run_executor,
	approved_marisol_request,
	cleanup_execution,
	dashboard_numbers,
	db_values,
)
from crm.erasure.erasure_test_fixtures import COLLEAGUE_EMAIL, build_marisol, cleanup_marisol
from crm.erasure.registry_model import content_marker, name_marker

LEAD_KEPT = ("status", "source", "lead_owner", "organization", "converted", "owner", "creation", "modified")
DEAL_KEPT = ("status", "deal_value", "probability", "deal_owner", "lead", "owner", "creation", "modified")


class ExecutorCase(IntegrationTestCase):
	def setUp(self):
		self.fx = build_marisol()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		cleanup_marisol()
		cleanup_execution(self.fx)

	def name(self, label):
		return self.fx.names[label]


class TestExecutor(ExecutorCase):
	def test_person_records(self):
		request = approved_marisol_request(self.fx)
		marker, erased = name_marker(request.name), content_marker(request.name)
		lead_before = db_values("CRM Lead", self.fx.lead, LEAD_KEPT)
		deal_before = db_values("CRM Deal", self.fx.deal_won, DEAL_KEPT)
		colleague_deal = db_values("CRM Deal", self.fx.colleague_deal, ("email", "first_name", "modified"))
		dashboard = dashboard_numbers()

		changes = run_executor(request)

		lead = db_values("CRM Lead", self.fx.lead, ("first_name", "lead_name", "email", "mobile_no", "image"))
		self.assertEqual(lead, {"first_name": marker, "lead_name": marker, "email": None, "mobile_no": None, "image": None})
		self.assertEqual(db_values("CRM Lead", self.fx.lead, LEAD_KEPT), lead_before)
		deal = db_values("CRM Deal", self.fx.deal_won, ("email", "mobile_no", "first_name"))
		self.assertEqual((deal["email"], deal["mobile_no"]), (None, None))
		self.assertEqual(db_values("CRM Deal", self.fx.deal_won, DEAL_KEPT), deal_before)
		self.assertEqual(db_values("CRM Deal", self.fx.colleague_deal, colleague_deal), colleague_deal)

		self.assertEqual(changes.renamed[0], ("Contact", self.fx.contact, marker))  # her name was its name
		self.assertEqual(frappe.db.get_value("CRM Deal", self.fx.deal_won, "contact"), marker)
		contact = db_values("Contact", marker, ("full_name", "first_name", "email_id", "mobile_no", "image"))
		self.assertEqual(contact, {"full_name": marker, "first_name": marker, "email_id": None, "mobile_no": None, "image": None})
		for child in ("Contact Email", "Contact Phone"):
			self.assertFalse(frappe.db.count(child, {"parent": marker, "parenttype": "Contact"}))
		her_row = db_values("CRM Contacts", self.name("colleague_deal_row_her"), ("full_name", "email", "contact"))
		self.assertEqual((her_row["full_name"], her_row["email"]), (marker, None))
		self.assertEqual(her_row["contact"], marker)  # still linked (renamed): dashboards count it
		kai_row = db_values("CRM Contacts", self.name("colleague_deal_row_kai"), ("email",))
		self.assertEqual(kai_row["email"], COLLEAGUE_EMAIL)

		self.assertEqual(changes.counts["CRM Lead"], 1)
		self.assertEqual(changes.counts["CRM Deal"], 2)
		self.assertIn(self.fx.lead, changes.docs)
		self.assertNotIn(self.fx.contact, changes.docs)  # Contact names spell her name
		self.assertEqual(dashboard_numbers(), dashboard)

	def test_activity_and_addresses(self):
		request = approved_marisol_request(self.fx)
		marker, erased = name_marker(request.name), content_marker(request.name)
		renamed = {old: new for _doctype, old, new in run_executor(request).renamed}

		comm = db_values("Communication", self.name("comm_cc_on_colleague_deal"), ("subject", "content", "cc", "recipients"))
		self.assertEqual((comm["subject"], comm["content"]), (erased, erased))
		self.assertEqual(comm["cc"], f"Kai <{COLLEAGUE_EMAIL}>")
		self.assertEqual(comm["recipients"], COLLEAGUE_EMAIL)
		self.assertIsNone(db_values("Communication", self.name("comm_from_her"), ("sender",))["sender"])
		self.assertIsNone(db_values("Communication", self.name("comm_sms"), ("phone_no",))["phone_no"])
		call = db_values("CRM Call Log", self.name("call_on_lead"), ("to", "from", "recording_url"))
		self.assertEqual((call["to"], call["recording_url"]), (marker, None))
		self.assertNotEqual(call["from"], marker)  # the rep's number stays
		self.assertEqual(db_values("CRM Call Log", self.name("call_from_her"), ("from",))["from"], marker)
		for doctype, label, field in (
			("FCRM Note", "note_on_deal", "title"),
			("CRM Task", "task_on_lead", "title"),
			("ToDo", "todo_on_task", "description"),
			("Comment", "comment_on_lead", "content"),
			("CRM Notification", "notification_on_lead", "message"),
			("Notification Log", "notification_log_on_deal", "subject"),
			("WA Message", "wa_to_her_profile", "message"),
		):
			with self.subTest(doctype=doctype):
				self.assertEqual(db_values(doctype, self.name(label), (field,))[field], erased)
		comment = db_values("Comment", self.name("comment_by_her"), ("comment_email", "comment_by"))
		self.assertEqual(comment, {"comment_email": None, "comment_by": None})
		self.assertEqual(db_values("WA Profile", self.name("wa_profile_her"), ("phone_number",))["phone_number"], marker)
		self.assertIsNone(db_values("WA Message", self.name("wa_from_her_number"), ("from",))["from"])

		hers = db_values("Address", renamed[self.name("address_hers")], ("address_line1", "city", "country"))
		self.assertEqual(hers, {"address_line1": erased, "city": erased, "country": "United States"})
		shared_name = renamed[self.name("address_shared")]  # shared, but titled after her: renamed too
		shared = db_values("Address", shared_name, ("address_line1",))
		self.assertEqual(shared["address_line1"], "1 Main St")
		links = frappe.get_all("Dynamic Link", {"parenttype": "Address", "parent": shared_name}, pluck="link_name")
		self.assertEqual(links, [self.fx.colleague_contact])
		titles = frappe.get_all(
			"Dynamic Link", {"link_doctype": "Contact", "link_name": marker}, pluck="link_title"
		)
		self.assertTrue(all(title in (None, "", marker) for title in titles))

	def test_exclusions(self):
		request = approved_marisol_request(self.fx, excluded=("comm_from_her", "address_hers"))
		comm_before = db_values("Communication", self.name("comm_from_her"), ("subject", "content", "sender", "modified"))
		address_before = db_values("Address", self.name("address_hers"), ("address_line1", "city"))
		comment_before = db_values("Comment", self.name("comment_on_comm"), ("content",))
		run_executor(request)
		self.assertEqual(db_values("Communication", self.name("comm_from_her"), comm_before), comm_before)
		self.assertEqual(db_values("Address", self.name("address_hers"), address_before), address_before)
		self.assertTrue(frappe.db.count("Dynamic Link", {"parenttype": "Address", "parent": self.name("address_hers")}))
		# reachable only through the excluded email thread: not a match, so untouched
		self.assertEqual(db_values("Comment", self.name("comment_on_comm"), ("content",)), comment_before)

	def test_rerun_changes_nothing(self):
		request = approved_marisol_request(self.fx)
		first = run_executor(request)
		self.assertGreater(first.total, 0)
		second = run_executor(request)
		self.assertEqual(dict(second.counts), {})
		note = db_values("FCRM Note", self.name("note_on_deal"), ("title", "content"))
		self.assertEqual(note, {"title": content_marker(request.name), "content": None})  # not doubled
