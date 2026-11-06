# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import json
from unittest.mock import patch

import frappe

from crm.erasure import verify
from crm.erasure.erasure_test_fixture_execution import approved_marisol_request, run_executor
from crm.erasure.erasure_test_fixtures import COLLEAGUE_EMAIL, HER_EMAILS, raw_insert
from crm.erasure.identifiers import Identifiers
from crm.erasure.post_commit import reindex_search
from crm.erasure.registry_model import name_marker
from crm.erasure.test_executor import ExecutorCase


class TestHiddenCopies(ExecutorCase):
	def version(self, ref_doctype, docname, data):
		return raw_insert({"doctype": "Version", "ref_doctype": ref_doctype, "docname": docname, "data": json.dumps(data)}).name

	def test_no_new_versions(self):
		request = approved_marisol_request(self.fx)
		before = set(frappe.get_all("Version", pluck="name"))
		with patch.object(frappe, "in_test", False):  # Frappe skips Versions in tests otherwise
			run_executor(request)
			self.assertFalse(set(frappe.get_all("Version", pluck="name")) - before)
			# control: versioning really is on here, so a save-based scrub would have been caught
			lead = frappe.get_doc("CRM Lead", self.name("namesake_lead"))
			lead.job_title = "Buyer"
			lead.save(ignore_permissions=True)
		self.assertTrue(frappe.db.exists("Version", {"ref_doctype": "CRM Lead", "docname": lead.name}))

	def test_versions(self):
		request = approved_marisol_request(self.fx)
		her_row = next(iter(self.fx.expected["CRM Contacts"] - {self.name("colleague_deal_row_her")}))
		on_lead = self.version("CRM Lead", self.fx.lead, {"changed": [["source", None, "Web"]]})
		on_deal = self.version(
			"CRM Deal",
			self.fx.deal_won,
			{
				"changed": [["status", "Open", "Won"], ["deal_value", 1, 5000], ["email", None, "x"], ["first_name", "a", "b"]],
				"added": [["contacts", {"name": her_row, "contact": self.fx.contact}]],
				"row_changed": [["contacts", 1, her_row, [["is_primary", 0, 1]]]],
			},
		)
		run_executor(request)
		self.assertFalse(frappe.db.exists("Version", on_lead))
		self.assertFalse(frappe.db.exists("Version", self.name("version_on_lead")))
		self.assertFalse(frappe.db.exists("Version", self.name("version_on_note")))
		data = json.loads(frappe.db.get_value("Version", on_deal, "data"))
		self.assertEqual(data["changed"], [["status", "Open", "Won"], ["deal_value", 1, 5000]])
		self.assertEqual((data["added"], data["row_changed"]), ([], []))
		# a colleague's deal: only the entry naming her email goes, and then the row is empty
		self.assertFalse(frappe.db.exists("Version", self.name("version_mentions_her")))
		near = frappe.db.get_value("Version", self.name("version_colleague"), "data")
		self.assertIn("jomarisol", near)

	def test_deleted_documents(self):
		run_executor(approved_marisol_request(self.fx))
		self.assertFalse(frappe.db.exists("Deleted Document", self.name("deleted_note")))
		self.assertTrue(frappe.db.exists("Deleted Document", self.name("deleted_other")))

	def test_global_search(self):
		request = approved_marisol_request(self.fx)
		rows = [
			("Contact", self.fx.contact, f"Marisol ||| {HER_EMAILS[0]}"),
			("Note", "gs-erasure-her", f"mail {HER_EMAILS[1]}"),
			("Note", "gs-erasure-near", "mail jomarisol.reyes@example.net"),
		]
		for doctype, name, content in rows:
			frappe.db.sql(
				"insert into `__global_search` (doctype, name, title, content, route, published) values (%s, %s, %s, %s, '', 0)",
				(doctype, name, name, content),
			)
		try:
			changes = run_executor(request)
			ids = Identifiers.from_rows(request.identifiers)
			reindex_search(changes, ids)
			contents = frappe.db.sql("select name, content from `__global_search` where content like %s", ("%example.net%",))
			self.assertFalse([name for name, content in contents if ids.matches_text(content)])
			self.assertFalse(frappe.db.sql("select 1 from `__global_search` where name = 'gs-erasure-her'"))
			self.assertTrue(frappe.db.sql("select 1 from `__global_search` where name = 'gs-erasure-near'"))
			renamed_contact = name_marker(request.name)  # her Contact was renamed away from her name
			indexed = frappe.db.sql("select content from `__global_search` where doctype = 'Contact' and name = %s", renamed_contact)
			self.assertTrue(indexed and name_marker(request.name) in indexed[0][0])
		finally:
			frappe.db.sql("delete from `__global_search` where name in ('gs-erasure-her', 'gs-erasure-near')")

	def test_queues_and_logs(self):
		run_executor(approved_marisol_request(self.fx))
		for label in ("queue_to_her", "queue_for_comm"):
			self.assertFalse(frappe.db.exists("Email Queue", self.name(label)))
			self.assertFalse(frappe.db.count("Email Queue Recipient", {"parent": self.name(label)}))
		for name in self.fx.hidden["Email Queue"]:
			self.assertFalse(frappe.db.exists("Email Queue", name))
		self.assertTrue(frappe.db.exists("Email Queue", self.name("queue_colleague")))
		recipients = frappe.get_all("Email Queue Recipient", {"parent": self.name("queue_colleague")}, pluck="recipient")
		self.assertEqual(recipients, [COLLEAGUE_EMAIL])
		self.assertFalse(frappe.db.exists("WA Log", self.name("wa_log_her")))
		self.assertTrue(frappe.db.exists("WA Log", self.name("wa_log_other")))
		self.assertFalse(frappe.db.exists("Error Log", self.name("error_log_her")))
		self.assertTrue(frappe.db.exists("Error Log", self.name("error_log_other")))

	def test_comments_column(self):
		request = approved_marisol_request(self.fx)
		old = [{"comment": f"Call {HER_EMAILS[0]}", "by": "rep", "name": "c-1"}, {"name": "c-2"}]
		for doctype, name in (("CRM Lead", self.fx.lead), ("CRM Deal", self.fx.colleague_deal)):
			frappe.db.set_value(doctype, name, "_comments", json.dumps(old), update_modified=False)
		run_executor(request)
		for doctype, name in (("CRM Lead", self.fx.lead), ("CRM Deal", self.fx.colleague_deal)):
			with self.subTest(doctype=doctype):
				stored = json.loads(frappe.db.get_value(doctype, name, "_comments"))
				self.assertEqual(stored, [{"name": "c-1"}, {"name": "c-2"}])

	def test_version_with_unreadable_data_is_kept_and_counted(self):
		request = approved_marisol_request(self.fx)
		broken = raw_insert({"doctype": "Version", "ref_doctype": "CRM Deal", "docname": self.fx.deal_won, "data": "{not json"}).name
		changes = run_executor(request)
		self.assertTrue(frappe.db.exists("Version", broken))
		self.assertEqual(changes.skipped.get("Version"), 1)

	def test_encoded_addresses_in_logs_are_purged_and_seen_by_the_residual_check(self):
		request = approved_marisol_request(self.fx)
		url_encoded = HER_EMAILS[0].replace("@", "%40")
		wa_log = raw_insert({"doctype": "WA Log", "message": "webhook", "request_data": f"email={url_encoded}"}).name
		html = {"doctype": "Error Log", "method": "erasure-test-fixture", "error": HER_EMAILS[1].lower().replace("@", "&#64;")}
		error_log = raw_insert(html).name
		run_executor(request)
		self.assertFalse(frappe.db.exists("WA Log", wa_log))
		self.assertFalse(frappe.db.exists("Error Log", error_log))
		raw_insert({"doctype": "Note", "title": "Erasure encoded probe", "content": f"see {url_encoded}"})
		ids = Identifiers.from_rows(request.identifiers)
		self.assertIn("tabNote", verify.residual_hits(ids, tables=["tabNote"]))
