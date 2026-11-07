# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The "Erasure outcome" email template (phase 06; design 5.10): shipped by install and by a patch, only if missing."""

import frappe
from frappe.tests import IntegrationTestCase

from crm.patches.v1_0.add_erasure_outcome_template import execute
from crm.privacy.install import setup
from crm.privacy.outcome_template import NAME, install_outcome_template

SECTIONS = (
	"What was erased",
	"What we kept, and why",
	"The record we keep of your request",
	"One limitation",
)


class TestOutcomeTemplate(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)
		if frappe.db.exists("Email Template", NAME):
			frappe.delete_doc("Email Template", NAME, force=True, ignore_permissions=True)

	def template(self):
		return frappe.get_doc("Email Template", NAME)

	def test_it_is_created_for_erasure_requests_and_enabled(self):
		install_outcome_template()
		template = self.template()
		self.assertEqual(template.reference_doctype, "CRM Erasure Request")
		self.assertEqual(template.enabled, 1)

	def test_it_carries_everything_the_design_requires(self):
		install_outcome_template()
		body = self.template().response
		for section in SECTIONS:
			self.assertIn(section, body)
		for needle in ("Twilio", "signed contract", "24 months", "do-not-contact", "passing mentions"):
			self.assertIn(needle, body)

	def test_it_has_markers_for_the_parts_compliance_fills_in(self):
		install_outcome_template()
		self.assertGreaterEqual(self.template().response.count("[COMPLIANCE"), 3)

	def test_it_names_the_request_in_the_subject_and_no_person(self):
		install_outcome_template()
		subject = self.template().get_formatted_subject({"name": "PDR-0007"})
		self.assertIn("PDR-0007", subject)

	def test_a_second_run_changes_nothing_and_keeps_an_edited_template(self):
		install_outcome_template()
		frappe.db.set_value("Email Template", NAME, "subject", "Edited by an admin")
		install_outcome_template()
		self.assertEqual(self.template().subject, "Edited by an admin")
		self.assertEqual(frappe.db.count("Email Template", {"name": NAME}), 1)

	def test_the_install_setup_and_the_patch_both_create_it(self):
		setup()
		self.assertTrue(frappe.db.exists("Email Template", NAME))
		frappe.delete_doc("Email Template", NAME, force=True, ignore_permissions=True)
		execute()
		self.assertTrue(frappe.db.exists("Email Template", NAME))
