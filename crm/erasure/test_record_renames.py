# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import json

import frappe

from crm.erasure import executor, jobs
from crm.erasure.erasure_test_fixture_execution import (
	REQUEST,
	approved_marisol_request,
	commits_recorded,
	dashboard_numbers,
	db_values,
	full_name_hits,
	run_executor,
)
from crm.erasure.erasure_test_fixtures import raw_insert
from crm.erasure.registry_model import name_marker
from crm.erasure.test_executor import ExecutorCase

HER_FULL_NAME = "Marisol Reyes"


class TestRenameGuard(ExecutorCase):
	def test_rename_allowed_only_inside_the_referencing_erasure(self):
		request = approved_marisol_request(self.fx)
		contact = self.fx.contact
		with self.assertRaises(frappe.ValidationError):
			frappe.rename_doc("Contact", contact, "Erasure Guard Probe", force=True, show_alert=False)
		with jobs.running_erasure("CRM-ERQ-1999-99999"), self.assertRaises(frappe.ValidationError):
			frappe.rename_doc("Contact", contact, "Erasure Guard Probe", force=True, show_alert=False)
		self.assertIsNone(frappe.flags.get("erasure_execution"))
		with jobs.running_erasure(request.name):
			frappe.rename_doc("Contact", contact, "Erasure Guard Probe", force=True, show_alert=False)
		self.assertTrue(frappe.db.exists("Contact", "Erasure Guard Probe"))
		self.assertIsNone(frappe.flags.get("erasure_execution"))  # cleared on exit


class TestRenames(ExecutorCase):
	def execute(self, request):
		with commits_recorded():
			jobs.execute_request(request.name)
		self.assertEqual(frappe.db.get_value(REQUEST, request.name, "status"), "Executed")
		return frappe.get_doc(REQUEST, request.name)

	def test_her_contact_and_address_are_renamed_and_links_follow(self):
		request = approved_marisol_request(self.fx)
		marker = name_marker(request.name)
		dashboard = dashboard_numbers()
		shared = self.name("address_shared")
		request = self.execute(request)

		self.assertFalse(frappe.db.exists("Contact", self.fx.contact))
		self.assertTrue(frappe.db.exists("Contact", marker))
		for deal in (self.fx.deal_won, self.fx.deal_open):
			self.assertEqual(frappe.db.get_value("CRM Deal", deal, "contact"), marker)
		self.assertEqual(db_values("CRM Contacts", self.name("colleague_deal_row_her"), ("contact",))["contact"], marker)
		kai_row = db_values("CRM Contacts", self.name("colleague_deal_row_kai"), ("contact",))
		self.assertEqual(kai_row["contact"], self.fx.colleague_contact)
		self.assertTrue(frappe.db.exists("Contact", self.fx.colleague_contact))
		self.assertTrue(frappe.db.exists("Contact", self.name("near_contact")))  # a namesake keeps her name
		self.assertFalse(frappe.db.exists("Address", self.name("address_hers")))
		self.assertTrue(frappe.db.exists("Address", {"name": ["like", f"{marker}%"]}))
		self.assertFalse(frappe.db.exists("Address", shared))  # shared but titled after her: renamed too
		timeline = frappe.get_all("Communication Link", {"parent": self.name("comm_timeline")}, pluck="link_name")
		self.assertEqual(timeline, [marker])
		refs = {(m.ref_doctype, m.ref_name) for m in request.matches}
		self.assertIn(("Contact", marker), refs)
		self.assertNotIn(("Contact", self.fx.contact), refs)
		self.assertNotIn(("Address", self.name("address_hers")), refs)
		self.assertFalse(frappe.get_all("Comment", {"content": ["like", f"%{HER_FULL_NAME}%"]}, pluck="name"))
		self.assertEqual(dashboard_numbers(), dashboard)

	def test_shared_address_titled_after_her_is_retitled_and_renamed(self):
		shared = self.name("address_shared")
		self.assertEqual(frappe.db.get_value("Address", shared, "address_title"), HER_FULL_NAME)  # as Frappe titled it
		frappe.db.sql(
			"insert into `__global_search` (doctype, name, title, content, route, published) values ('Address', %s, %s, 'City/Town : Oakland', '', 0)",
			(shared, shared),
		)
		request = self.execute(approved_marisol_request(self.fx))
		marker = name_marker(request.name)
		new = next(m.ref_name for m in request.matches if m.ref_doctype == "Address" and m.action == "unlink")
		self.assertTrue(new.startswith(marker))
		self.assertEqual(db_values("Address", new, ("address_title", "address_line1")), {"address_title": marker, "address_line1": "1 Main St"})
		links = frappe.get_all("Dynamic Link", {"parenttype": "Address", "parent": new}, pluck="link_name")
		self.assertEqual(links, [self.fx.colleague_contact])  # the colleague's link stays, hers went
		self.assertFalse(frappe.db.sql("select 1 from `__global_search` where name = %s", shared))
		self.assertFalse(frappe.db.sql("select 1 from `tabSeries` where name like %s", (f"{HER_FULL_NAME}%",)))

	def test_shared_address_titled_otherwise_is_untouched(self):
		links = [{"link_doctype": "Contact", "link_name": self.fx.contact}, {"link_doctype": "Contact", "link_name": self.fx.colleague_contact}]
		office = raw_insert(
			{"doctype": "Address", "name": "Kai Office-Billing", "address_title": "Kai Office", "address_type": "Billing", "address_line1": "2 Side St", "city": "Oakland", "country": "United States", "links": links}
		).name
		request = self.execute(approved_marisol_request(self.fx))
		self.assertIn(("Address", office), {(m.ref_doctype, m.ref_name) for m in request.matches})
		self.assertEqual(db_values("Address", office, ("address_title", "address_line1")), {"address_title": "Kai Office", "address_line1": "2 Side St"})
		remaining = frappe.get_all("Dynamic Link", {"parenttype": "Address", "parent": office}, pluck="link_name")
		self.assertEqual(remaining, [self.fx.colleague_contact])

	def test_no_row_spells_her_full_name_after_execution(self):
		request = approved_marisol_request(self.fx)
		self.assertTrue(full_name_hits(self.fx, HER_FULL_NAME))  # control: the oracle sees her now
		self.execute(request)
		self.assertEqual(full_name_hits(self.fx, HER_FULL_NAME), [])

	def test_version_values_follow_only_links_to_the_renamed_record(self):
		def version(ref_doctype, docname, data):
			return raw_insert({"doctype": "Version", "ref_doctype": ref_doctype, "docname": docname, "data": json.dumps(data)}).name

		on_deal = version("CRM Deal", self.fx.deal_won, {"changed": [["contact", None, HER_FULL_NAME], ["status", "a", "b"]]})
		namesake = {"changed": [["lead_name", "", HER_FULL_NAME]]}  # a Data field of another person's lead
		on_namesake = version("CRM Lead", self.name("namesake_lead"), namesake)
		request = self.execute(approved_marisol_request(self.fx))
		deal_data = json.loads(frappe.db.get_value("Version", on_deal, "data"))
		self.assertEqual(deal_data["changed"], [["contact", None, name_marker(request.name)], ["status", "a", "b"]])
		self.assertEqual(json.loads(frappe.db.get_value("Version", on_namesake, "data")), namesake)

	def test_rerun_renames_nothing(self):
		request = self.execute(approved_marisol_request(self.fx))
		contacts = frappe.db.count("Contact")
		with commits_recorded():
			changes = run_executor(request)
		self.assertEqual(dict(changes.counts), {})
		self.assertEqual(frappe.db.count("Contact"), contacts)
		self.assertTrue(frappe.db.exists("Contact", name_marker(request.name)))

	def test_executor_without_the_job_flag_cannot_rename(self):
		request = approved_marisol_request(self.fx)
		with self.assertRaises(executor.ErasureStepFailed):
			executor.run(request)
