# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import today

from crm.api import erasure as api
from crm.erasure.erasure_test_fixtures import raw_insert
from crm.erasure.match_rows import format_key
from crm.fcrm.doctype.crm_erasure_request.erasure_test_fixtures import (
	MANAGER,
	PO,
	REP,
	REP2,
	as_user,
	ensure_users,
	make_deal,
	make_lead,
)

EMAIL, PHONE = "dana.erasure@example.net", "+1 415-555-0142"
EMAIL_SPELLED_BY_REP = EMAIL.upper()


class ErasureApiCase(IntegrationTestCase):
	"""Shared setup: REP's lead with her email and one email to her (no tests here)"""

	def setUp(self):
		ensure_users()
		self.lead = make_lead("Dana")
		frappe.db.set_value("CRM Lead", self.lead.name, "email", EMAIL, update_modified=False)
		self.comm = self.email_to(EMAIL)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def email_to(self, recipients):
		return raw_insert(
			{
				"doctype": "Communication",
				"communication_type": "Communication",
				"subject": "Hi",
				"sent_or_received": "Sent",
				"status": "Linked",
				"sender": REP,
				"recipients": recipients,
			}
		).name

	def log(self, user=REP, emails=(EMAIL_SPELLED_BY_REP,), phones=(PHONE,), source=None):
		with as_user(user):
			return api.log_request(
				"CRM Lead", source or self.lead.name, "Dana Test", today(), list(emails), list(phones)
			)

	def keys(self, preview):
		return {row["key"] for group in preview["groups"] for row in group["rows"]}


class TestErasureApi(ErasureApiCase):
	def test_log_request_stores_normalized_identifiers_and_matches(self):
		preview = self.log()
		request = frappe.get_doc("CRM Erasure Request", preview["name"])
		self.assertEqual((request.status, request.requested_by), ("Draft", REP))
		self.assertEqual(
			[(r.kind, r.normalized) for r in request.identifiers],
			[("Email", EMAIL), ("Phone", "+14155550142")],
		)
		stored = {(m.ref_doctype, m.ref_name): m.reason for m in request.matches}
		self.assertEqual(stored[("CRM Lead", self.lead.name)], "linked")
		self.assertEqual(stored[("Communication", self.comm)], "email")
		listed = self.keys(preview)
		self.assertTrue(listed <= {format_key(*key) for key in stored})
		unreadable = sum(group["unreadable"] for group in preview["groups"])
		self.assertEqual(len(listed) + unreadable, len(stored))

	def test_log_request_rejects_bad_or_missing_identifiers_without_echoing_them(self):
		for emails, phones in ((["not-an-email-zz9"], []), ([], ["12-34"]), ([], []), ([" "], [])):
			with (
				self.subTest(emails=emails, phones=phones),
				self.assertRaises(frappe.ValidationError) as caught,
			):
				self.log(emails=emails, phones=phones)
			self.assertNotIn("zz9", str(caught.exception))
		self.assertFalse(frappe.db.exists("CRM Erasure Request", {"source_docname": self.lead.name}))

	def test_log_request_needs_create_permission_and_a_readable_source(self):
		with self.assertRaises(frappe.PermissionError):
			self.log(user=REP2)  # cannot read REP's lead
		with self.assertRaises(frappe.PermissionError):
			self.log(user=MANAGER)  # may read requests, not log them
		with self.assertRaises(frappe.PermissionError):
			self.log(source="CRM-LEAD-NOPE-0001")

	def test_get_preview_is_for_the_requester_or_a_privacy_officer(self):
		name = self.log()["name"]
		for user in (REP, PO):
			with self.subTest(user=user), as_user(user):
				self.assertEqual(api.get_preview(name)["name"], name)
		for user in (REP2, MANAGER):
			with self.subTest(user=user), as_user(user), self.assertRaises(frappe.PermissionError):
				api.get_preview(name)

	def test_set_exclusions_by_requester_on_draft(self):
		name, key = self.log()["name"], format_key("Communication", self.comm)
		with as_user(REP):
			preview = api.set_exclusions(name, [key])
		excluded = {r["key"] for g in preview["groups"] for r in g["rows"] if r["excluded"]}
		self.assertEqual(excluded, {key})
		with as_user(REP):
			api.set_exclusions(name, [])
		self.assertFalse(any(m.excluded for m in frappe.get_doc("CRM Erasure Request", name).matches))
		for bad in (["Communication"], ["::x"], [format_key("Communication", "not-a-match")]):
			with self.subTest(bad=bad), as_user(REP), self.assertRaises(frappe.ValidationError):
				api.set_exclusions(name, bad)

	def test_set_exclusions_denied_to_others_and_after_draft(self):
		name, key = self.log()["name"], format_key("Communication", self.comm)
		for user in (REP2, PO, MANAGER):
			with self.subTest(user=user), as_user(user), self.assertRaises(frappe.PermissionError):
				api.set_exclusions(name, [key])
		with as_user(REP):
			self.assertEqual(api.submit_for_approval(name)["status"], "Pending Approval")
			with self.assertRaises(frappe.ValidationError):
				api.set_exclusions(name, [key])
		self.assertFalse(any(m.excluded for m in frappe.get_doc("CRM Erasure Request", name).matches))

	def test_submit_for_approval_holds_on_her_open_deal(self):
		deal = make_deal(lead=self.lead.name)
		name = self.log()["name"]
		with as_user(REP2), self.assertRaises(frappe.PermissionError):
			api.submit_for_approval(name)
		with as_user(REP):
			result = api.submit_for_approval(name)
		self.assertEqual((result["status"], result["hold_reason"]), ("On Hold", deal.name))

	def test_refresh_matches_flags_new_rows_and_keeps_exclusions(self):
		name = self.log()["name"]
		with as_user(REP):
			api.set_exclusions(name, [format_key("Communication", self.comm)])
		new_comm = self.email_to(f"Dana <{EMAIL}>")
		with as_user(REP2), self.assertRaises(frappe.PermissionError):
			api.refresh_matches(name)
		with as_user(REP):
			preview = api.refresh_matches(name)
		rows = {r["key"]: r for g in preview["groups"] for r in g["rows"]}
		self.assertEqual(rows[format_key("Communication", new_comm)]["new_since_logging"], 1)
		self.assertEqual(rows[format_key("Communication", self.comm)]["excluded"], 1)
		self.assertEqual(rows[format_key("CRM Lead", self.lead.name)]["new_since_logging"], 0)
