# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The test helper removes only the Error Logs a test created; it must be safe on a site with real logs."""

import frappe
from frappe.tests import IntegrationTestCase

from crm.privacy.tests.make_test_user import purge_error_logs

DOCTYPE = "CRM Erasure Request"


def make_log(title, reference_name, created=None):
	log = frappe.log_error(title, "RuntimeError", reference_doctype=DOCTYPE, reference_name=reference_name)
	if created:
		frappe.db.set_value("Error Log", log.name, "creation", created, update_modified=False)
		frappe.db.commit()
	return log.name


class TestPurgeErrorLogs(IntegrationTestCase):
	def tearDown(self):
		frappe.db.delete("Error Log", {"method": ["like", "ZZ-PURGE-%"]})
		frappe.db.commit()

	def test_it_removes_only_this_tests_logs_for_its_requests(self):
		old = make_log("ZZ-PURGE-old", "PDR-9001", created=frappe.utils.add_days(frappe.utils.now(), -5))
		started = frappe.utils.add_to_date(frappe.utils.now_datetime(), seconds=-1)
		mine = make_log("ZZ-PURGE-mine", "PDR-9001")
		lookup = make_log("ZZ-PURGE-lookup", None)
		someone_elses = make_log("ZZ-PURGE-other", "PDR-9002")
		purge_error_logs(started, ["PDR-9001"])
		left = set(frappe.get_all("Error Log", filters={"method": ["like", "ZZ-PURGE-%"]}, pluck="name"))
		self.assertEqual(left, {old, someone_elses})
		self.assertNotIn(mine, left)
		self.assertNotIn(lookup, left)
