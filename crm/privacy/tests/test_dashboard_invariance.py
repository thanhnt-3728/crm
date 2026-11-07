# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Anti-goal of design 2: no pipeline, revenue, funnel or count on the dashboard moves because of an erasure.

The Marisol scenario goes through the whole lifecycle (submit, hold, remove her from the open deal, approve, job,
close). Every dashboard number, as Administrator and as the deal owner, for all time and for this month, is read
before and after and must be identical; so must the non-personal columns of every lead and deal.
"""

import frappe

from crm.privacy.tests import erasure_fixture
from crm.privacy.tests.dashboard_snapshot import dashboard_snapshot
from crm.privacy.tests.erasure_lifecycle_case import LifecycleCase

# What reports read, plus `modified`: an erasure writes with `update_modified=False`, so history shows no edit.
KEPT_COLUMNS = {
	"CRM Lead": ("name", "creation", "modified", "owner", "status", "lead_owner", "source", "territory", "organization"),
	"CRM Deal": ("name", "creation", "modified", "owner", "status", "deal_owner", "source", "territory",
		"organization", "deal_value", "currency", "exchange_rate", "closed_date", "lost_reason", "probability"),
}  # fmt: skip


def kept_columns() -> dict:
	out = {}
	for doctype, columns in KEPT_COLUMNS.items():
		have = [c for c in columns if frappe.db.has_column(doctype, c)]
		out[doctype] = frappe.db.get_all(doctype, fields=have, order_by="name", limit_page_length=0)
	return out


class TestDashboardInvariance(LifecycleCase):
	def setUp(self):
		"""The baseline is read before the request is logged: submit, hold and the removal from the open deal are
		part of the lifecycle the numbers must survive."""
		real = erasure_fixture.log_request

		def baseline_then_log(case, p):
			case.users = ("Administrator", p.rep)
			case.before = dashboard_snapshot(case.users)
			return real(case, p)

		self.addCleanup(setattr, erasure_fixture, "log_request", real)
		erasure_fixture.log_request = baseline_then_log
		super().setUp()

	def test_the_baseline_is_not_empty(self):
		"""A comparison of two empty dashboards proves nothing."""
		admin = self.before[("Administrator", "all time")]
		self.assertGreaterEqual(admin["number_chart:total_leads"]["value"], 2)
		self.assertGreaterEqual(admin["number_chart:won_deals"]["value"], 2)
		self.assertGreater(admin["number_chart:average_deal_value"]["value"], 0)
		rep = self.before[(self.p.rep, "all time")]
		self.assertEqual(
			rep["number_chart:ongoing_deals"]["value"], 1
		)  # her Negotiation deal, owned by the rep
		self.assertTrue(any(item["data"] for item in admin["dashboard"]))

	def test_no_dashboard_number_moves_through_the_whole_lifecycle(self):
		columns = kept_columns()
		self.approve_and_run()
		self.assertEqual(self.stored("status").status, "Erased")
		self.assertEqual(self.close_and_finish()["status"], "Closed")
		self.assertEqual(
			frappe.db.get_value("CRM Lead", self.p.lead, "first_name"), f"Erased person {self.request}"
		)  # it did erase

		after = dashboard_snapshot(self.users)
		self.assertEqual(set(after), set(self.before))
		for key, data in self.before.items():
			for chart, value in data.items():
				with self.subTest(user=key[0], period=key[1], chart=chart):
					self.assertEqual(after[key][chart], value)
		self.assertEqual(kept_columns(), columns)
