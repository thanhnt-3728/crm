# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The signed-contract exception and what must not move (phase 05 step 10, design 5.11, anti-goals)."""

import frappe
from frappe.utils import add_months, today

from crm.api.erasure_review import set_contract_references
from crm.privacy.tests.erasure_run_case import ExecutorCase
from crm.privacy.tests.make_test_user import as_user

COUNTS = ("CRM Lead", "CRM Deal", "CRM Organization", "CRM Status Change Log", "CRM Lead Status")


class TestRetainedContract(ExecutorCase):
	def test_her_name_and_the_reference_are_kept_until_the_delete_after_date(self):
		frappe.db.set_single_value("CRM Privacy Settings", "contract_retention_months", 36)
		as_user(self.compliance, set_contract_references, self.request, ["CT-1001", "CT-1002"])
		self.approve_and_run()
		rows = frappe.get_all(
			"CRM Retained Contract", {"request": self.request},
			["person_name", "contract_reference", "delete_after"], order_by="contract_reference",
		)  # fmt: skip
		self.assertEqual([r.contract_reference for r in rows], ["CT-1001", "CT-1002"])
		for row in rows:
			self.assertEqual(row.person_name, "Marisol Vega")
			self.assertEqual(str(row.delete_after), add_months(today(), 36))

	def test_without_references_nothing_is_retained(self):
		self.approve_and_run()
		self.assertEqual(frappe.db.count("CRM Retained Contract"), 0)
		self.assertEqual(self.stored("status").status, "Erased")

	def test_her_name_is_kept_nowhere_else_in_the_retained_row(self):
		frappe.db.set_single_value("CRM Privacy Settings", "contract_retention_months", 12)
		as_user(self.compliance, set_contract_references, self.request, ["CT-1"])
		self.approve_and_run()
		row = frappe.get_all("CRM Retained Contract", ["*"])[0]
		self.assertNotIn(self.p.email, " ".join(str(v) for v in row.values()))


class TestNothingTheDashboardReadsMoves(ExecutorCase):
	def test_counts_status_values_owners_and_dates_are_identical(self):
		before = {t: frappe.db.count(t) for t in COUNTS}
		fields = ["name", "status", "creation", "modified", "owner"]
		deals = frappe.get_all(
			"CRM Deal",
			fields=[*fields, "deal_value", "deal_owner", "source", "territory", "closed_date"],
			order_by="name",
		)
		leads = frappe.get_all(
			"CRM Lead", fields=[*fields, "lead_owner", "source", "territory"], order_by="name"
		)
		logs = frappe.get_all("CRM Status Change Log", fields=["*"], order_by="name")
		self.approve_and_run()
		self.assertEqual(self.stored("status").status, "Erased")
		self.assertEqual({t: frappe.db.count(t) for t in COUNTS}, before)
		self.assertEqual(frappe.get_all("CRM Deal", fields=list(deals[0]), order_by="name"), deals)
		self.assertEqual(frappe.get_all("CRM Lead", fields=list(leads[0]), order_by="name"), leads)
		self.assertEqual(frappe.get_all("CRM Status Change Log", fields=["*"], order_by="name"), logs)
