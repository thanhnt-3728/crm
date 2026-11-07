# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""What matching and the impact counts reveal to a user who cannot read every record (RT-5), and who may
call the matching and submit APIs at all (RT-1)."""

import json

import frappe

from crm.api.erasure_requests import (
	get_identifier_impact,
	get_request,
	set_identifier_excluded,
	set_match_confirmed,
	suggest_matches,
)
from crm.privacy.tests.make_test_user import (
	RequestTestCase,
	as_user,
	make_lead,
	make_request,
	match_rows,
)

LEAD = "CRM Lead"


def make_communication(sender, recipients="sales@northpine.example"):
	return frappe.get_doc(
		{
			"doctype": "Communication",
			"communication_type": "Communication",
			"communication_medium": "Email",
			"sent_or_received": "Received",
			"sender": sender,
			"recipients": recipients,
			"subject": "Hello",
			"content": "Hello",
		}
	).insert(ignore_permissions=True)


def make_call_log(from_number, to_number):
	return frappe.get_doc(
		{
			"doctype": "CRM Call Log",
			"id": frappe.generate_hash(length=10),
			"from": from_number,
			"to": to_number,
			"type": "Incoming",
			"status": "Completed",
			"telephony_medium": "Manual",
		}
	).insert(ignore_permissions=True)


class TestScopedMatching(RequestTestCase):
	def setUp(self):
		super().setUp()
		self.outside = make_lead(owner=self.other, first_name="Outside", email="scoped@example.com")
		self.inside = make_lead(owner=self.logger, first_name="Inside", email="scoped@example.com")
		self.name = make_request(self.logger, emails=["scoped@example.com"])

	def test_the_precondition_holds(self):
		self.assertFalse(frappe.has_permission(LEAD, "read", self.outside, user=self.logger))
		self.assertTrue(frappe.has_permission(LEAD, "read", self.inside, user=self.logger))

	def test_the_logger_gets_no_suggestion_for_a_record_outside_their_scope(self):
		shown = as_user(self.logger, suggest_matches, self.name)
		self.assertEqual([m["reference_name"] for m in shown["matches"]], [self.inside])
		self.assertEqual(set(match_rows(self.name)), {(LEAD, self.inside)})

	def test_nothing_about_the_hidden_record_leaves_in_the_response(self):
		shown = as_user(self.logger, suggest_matches, self.name)
		text = json.dumps(shown, default=str)
		self.assertNotIn(self.outside, text)
		self.assertNotIn("Outside", text)

	def test_compliance_sees_every_candidate(self):
		as_user(self.compliance, suggest_matches, self.name)
		self.assertEqual(set(match_rows(self.name)), {(LEAD, self.inside), (LEAD, self.outside)})

	def test_a_row_compliance_added_stays_hidden_from_the_logger(self):
		as_user(self.compliance, suggest_matches, self.name)
		shown = as_user(self.logger, get_request, self.name)
		self.assertEqual([m["reference_name"] for m in shown["matches"]], [self.inside])
		self.assertNotIn("Outside", json.dumps(shown, default=str))

	def test_the_logger_cannot_confirm_a_row_they_cannot_read(self):
		as_user(self.compliance, suggest_matches, self.name)
		row = match_rows(self.name)[(LEAD, self.outside)]
		with self.assertRaises(frappe.PermissionError):
			as_user(self.logger, set_match_confirmed, self.name, row.name, True)
		self.assertEqual(match_rows(self.name)[(LEAD, self.outside)].confirmed, 0)

	def test_impact_counts_only_what_the_logger_can_read_and_hides_mail_counts(self):
		make_communication("scoped@example.com")
		make_call_log("+15305550101", "+15305550102")
		(row,) = as_user(self.logger, get_identifier_impact, self.name)
		self.assertEqual((row["kind"], row["value"], row["records"]), ("Email", "scoped@example.com", 1))
		self.assertIsNone(row["communications"])
		self.assertIsNone(row["call_logs"])

	def test_compliance_gets_every_count(self):
		make_communication("scoped@example.com")
		make_communication("someone@example.com", recipients="Scoped <scoped@example.com>, x@example.com")
		make_communication("bigscoped@example.com")
		(row,) = as_user(self.compliance, get_identifier_impact, self.name)
		self.assertEqual(row["records"], 2)
		self.assertEqual(row["communications"], 2)
		self.assertEqual(row["call_logs"], 0)

	def test_call_logs_are_counted_by_normalized_number(self):
		name = make_request(self.logger, emails=None, phones=["(530) 555-0101"])
		make_call_log("+15305550101", "+15305550102")
		make_call_log("+15305550103", "530-555-0101")
		make_call_log("+15305550104", "+15305550105")
		(row,) = as_user(self.compliance, get_identifier_impact, name)
		self.assertEqual(row["call_logs"], 2)

	def test_a_wildcard_value_counts_nothing(self):
		doc = frappe.get_doc("CRM Erasure Request", self.name)
		from crm.privacy.request_status import server_write

		doc.append("identifiers", {"kind": "Email", "value": "%@example.com", "normalized": "%@example.com"})
		with server_write():
			doc.save(ignore_permissions=True)
		make_communication("scoped@example.com")
		rows = as_user(self.compliance, get_identifier_impact, self.name)
		wildcard = next(r for r in rows if r["value"] == "%@example.com")
		self.assertEqual((wildcard["records"], wildcard["communications"], wildcard["call_logs"]), (0, 0, 0))

	def test_impact_reports_the_excluded_flag(self):
		identifier = frappe.get_doc("CRM Erasure Request", self.name).identifiers[0].name
		as_user(self.logger, set_identifier_excluded, self.name, identifier, True)
		(row,) = as_user(self.logger, get_identifier_impact, self.name)
		self.assertEqual(row["excluded"], 1)
		self.assertEqual(row["row"], identifier)


class TestHierarchyScopedMatching(RequestTestCase):
	"""With the sales hierarchy on, a rep sees their own subtree only; matching follows the same hook."""

	def test_a_lead_owned_by_the_managers_other_report_is_not_suggested(self):
		boss = frappe.get_doc({"doctype": "CRM Sales Hierarchy", "user": self.manager, "is_group": 1})
		boss.insert(ignore_permissions=True)
		member = {"doctype": "CRM Sales Hierarchy", "user": self.logger, "reports_to": boss.name}
		frappe.get_doc(member).insert(ignore_permissions=True)
		settings = frappe.get_single("FCRM Settings")
		settings.enable_sales_hierarchy = 1
		settings.save(ignore_permissions=True)
		bosss_lead = make_lead(owner=self.manager, first_name="Boss", email="tree@example.com")
		own = make_lead(owner=self.logger, first_name="Own", email="tree@example.com")
		name = make_request(self.logger, emails=["tree@example.com"])
		shown = as_user(self.logger, suggest_matches, name)
		self.assertEqual([m["reference_name"] for m in shown["matches"]], [own])
		self.assertNotIn(bosss_lead, json.dumps(shown, default=str))
		as_user(self.compliance, suggest_matches, name)
		self.assertEqual(
			{m.reference_name for m in frappe.get_doc("CRM Erasure Request", name).matches},
			{own, bosss_lead},
		)
