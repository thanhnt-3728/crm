# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Shared addresses [I3], a match deleted before approval, and a re-run after a partial failure (phase 05)."""

import frappe

from crm.privacy.erasure import scrub_files
from crm.privacy.erasure.plan_builder import build_plan
from crm.privacy.erasure.scrub_context import ScrubContext
from crm.privacy.tests.erasure_run_case import ExecutorCase


class EdgeCase(ExecutorCase):
	def shared_address(self, title: str) -> str:
		return (
			frappe.get_doc(
				{
					"doctype": "Address",
					"address_title": title,
					"address_type": "Office",
					"address_line1": "9 Main St",
					"city": "Chico",
					"country": "United States",
					"links": [
						{"link_doctype": "Contact", "link_name": self.p.contact},
						{"link_doctype": "Contact", "link_name": self.p.colleague},
					],
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def links_of(self, address: str) -> list:
		return frappe.get_all("Dynamic Link", {"parenttype": "Address", "parent": address}, pluck="link_name")


class TestSharedAddress(EdgeCase):
	def test_only_her_link_goes_and_the_colleagues_address_survives(self):
		name = self.shared_address("Sierra Office")
		self.approve_and_run()
		self.assertEqual(self.stored("status").status, "Erased")
		self.assertEqual(self.links_of(name), [self.p.colleague])  # her contact's row is gone
		address = frappe.db.get_value(
			"Address", name, ["address_title", "address_line1", "city"], as_dict=True
		)
		self.assertEqual(
			address, {"address_title": "Sierra Office", "address_line1": "9 Main St", "city": "Chico"}
		)

	def test_the_docname_is_renamed_only_when_it_holds_her_value(self):
		holds = self.shared_address("Marisol Vega")  # docname "Marisol Vega-Office"
		self.approve_and_run()
		self.assertFalse(frappe.db.exists("Address", holds))
		renamed = frappe.get_all("Address", {"address_line1": "9 Main St"}, ["name", "address_title", "city"])
		self.assertEqual(len(renamed), 1)
		self.assertTrue(renamed[0].name.startswith(f"Erased person {self.request}"))
		self.assertEqual(renamed[0].city, "Chico")  # fields untouched
		self.assertEqual(self.links_of(renamed[0].name), [self.p.colleague])


class TestDeletedBeforeApproval(EdgeCase):
	def test_a_confirmed_record_deleted_earlier_is_found_through_its_deleted_copy(self):
		frappe.delete_doc("CRM Deal", self.p.won, force=True, ignore_permissions=True)
		copies = frappe.get_all(
			"Deleted Document", {"deleted_name": self.p.won}, pluck="name", order_by="creation desc"
		)
		self.approve_and_run()
		self.assertEqual(self.stored("status").status, "Erased")
		self.assertFalse(frappe.db.exists("Deleted Document", copies[0]))


class TestRerun(EdgeCase):
	def test_a_file_row_that_is_already_gone_is_skipped(self):
		plan = build_plan(frappe.get_doc("CRM Erasure Request", self.request))
		frappe.db.delete(
			"File", {"name": self.activity.history.file_lead}
		)  # as if an earlier run got this far
		ctx = ScrubContext(self.request, plan)
		scrub_files.scrub(plan, ctx)
		self.assertEqual(
			len(ctx.pending_files), 4
		)  # photo, deal file, email attachment and voice note: not the missing one
		self.assertFalse(frappe.db.exists("File", {"name": ["in", plan.targets["files"]]}))
