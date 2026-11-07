# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The "plan changed" failure is stored in English whatever the site language, so the UI can tell it from other
failures and show its own translated banner (phase 07 fix round 2, L4)."""

from unittest.mock import patch

import frappe

from crm.privacy.tests.test_erasure_job_guards import PLAN_CHANGED, GuardCase


class TestPlanChangedMarker(GuardCase):
	def test_the_stored_error_does_not_depend_on_the_translation(self):
		match = {"parent": self.request, "reference_name": self.p.contact}
		frappe.db.set_value("CRM Erasure Match", match, "confirmed", 0)
		with patch("crm.privacy.erasure.executor_checks._", lambda text: f"[translated] {text}"):
			self.run_job()
		self.assertEqual(self.stored("erasure_error").erasure_error, PLAN_CHANGED)
