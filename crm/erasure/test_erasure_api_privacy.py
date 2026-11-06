# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
"""API review fixes: no enumeration through previews or identifiers, bounded scans, derived exclusions"""

from unittest.mock import patch

import frappe

from crm.api import erasure as api
from crm.erasure.erasure_test_fixtures import raw_insert
from crm.erasure.match_rows import format_key
from crm.erasure.test_erasure_api import EMAIL, PHONE, ErasureApiCase
from crm.fcrm.doctype.crm_erasure_request.erasure_test_fixtures import PO, REP, as_user


def rows_by_key(preview) -> dict:
	return {row["key"]: row for group in preview["groups"] for row in group["rows"]}


class TestErasureApiPrivacy(ErasureApiCase):
	def test_unreadable_rows_are_only_counted(self):
		name, lead_key = self.log()["name"], format_key("CRM Lead", self.lead.name)
		with as_user(PO):
			self.assertFalse(frappe.has_permission("CRM Lead", "read", doc=self.lead.name))
			preview = api.get_preview(name)
		lead_group = next(g for g in preview["groups"] if g["doctype"] == "CRM Lead")
		self.assertEqual((lead_group["count"], lead_group["unreadable"], lead_group["rows"]), (1, 1, []))
		self.assertNotIn(self.lead.name, frappe.as_json(preview))
		with as_user(REP):  # positive control: the owner reads her lead, so it is listed with its title
			row = rows_by_key(api.get_preview(name))[lead_key]
		self.assertEqual(row["title"], frappe.db.get_value("CRM Lead", self.lead.name, "lead_name"))
		self.assertNotIn(EMAIL, frappe.as_json(preview).lower())

	def test_identifiers_must_belong_to_the_source(self):
		for emails, phones in ((["someone.else.zz9@example.net"], []), ([], ["+1 415-555-0177"])):
			with self.subTest(emails=emails), self.assertRaises(frappe.ValidationError) as caught:
				self.log(emails=emails, phones=phones)
			self.assertNotIn("zz9", str(caught.exception))
			self.assertNotIn("0177", str(caught.exception))
		self.assertFalse(frappe.db.exists("CRM Erasure Request", {"source_docname": self.lead.name}))
		frappe.db.set_value("CRM Lead", self.lead.name, "mobile_no", "(415) 555-0142", update_modified=False)
		self.assertTrue(self.log(emails=["other.zz9@example.net"], phones=[PHONE])["name"])  # positive

	def test_a_contact_source_matches_through_its_email_rows(self):
		contact = frappe.get_doc(
			{"doctype": "Contact", "first_name": "Dana", "email_ids": [{"email_id": EMAIL, "is_primary": 1}]}
		).insert(ignore_permissions=True)
		frappe.db.set_value("Contact", contact.name, "email_id", None, update_modified=False)
		with as_user(REP):
			preview = api.log_request("Contact", contact.name, "Dana", frappe.utils.today(), [EMAIL], [])
		self.assertTrue(preview["name"])

	def test_scan_and_mutating_endpoints_are_post_only(self):
		allowed = frappe.allowed_http_methods_for_whitelisted_func
		for fn in (
			api.log_request,
			api.refresh_matches,
			api.set_exclusions,
			api.submit_for_approval,
			api.get_preview,
		):
			with self.subTest(fn=fn.__name__):
				self.assertEqual(allowed[fn], ["POST"])

	def test_preview_reuses_the_hidden_counts_of_the_last_discovery(self):
		name = self.log()["name"]
		with as_user(REP), patch("crm.erasure.discovery.find") as find:
			preview = api.get_preview(name)
		find.assert_not_called()
		self.assertIn("Version", preview["hidden"])

	def test_refresh_checks_the_actor_before_running_discovery(self):
		name = self.log()["name"]
		with as_user(REP):
			api.submit_for_approval(name)  # Pending Approval: only a decider may change matches now
			with patch("crm.api.erasure.discover") as discover, self.assertRaises(frappe.PermissionError):
				api.refresh_matches(name)
		discover.assert_not_called()

	def test_a_corrupt_identifier_is_a_validation_error_without_its_value(self):
		name = self.log()["name"]
		row = frappe.get_all("CRM Erasure Identifier", {"parent": name, "kind": "Email"}, pluck="name")[0]
		frappe.db.set_value("CRM Erasure Identifier", row, {"value": "bad-zz9", "normalized": "bad-zz9"})
		with as_user(REP), self.assertRaises(frappe.ValidationError) as caught:
			api.refresh_matches(name)
		self.assertNotIn("zz9", str(caught.exception))

	def test_excluding_a_thread_excludes_what_was_found_only_through_it(self):
		comment = raw_insert(
			{
				"doctype": "Comment",
				"comment_type": "Comment",
				"reference_doctype": "Communication",
				"reference_name": self.comm,
				"content": "Noted",
				"comment_email": REP,
			}
		).name
		name, comm_key = self.log()["name"], format_key("Communication", self.comm)
		self.assertIn(("Comment", comment), self.stored(name))
		with as_user(REP):
			rows = rows_by_key(api.set_exclusions(name, [comm_key]))
		self.assertEqual(rows[comm_key]["excluded"], 1)
		self.assertEqual(self.stored(name)[("Communication", self.comm)], 1)
		self.assertEqual(self.stored(name)[("Comment", comment)], 1)  # listed, excluded through the thread
		with as_user(REP):
			api.set_exclusions(name, [])
		self.assertEqual(self.stored(name)[("Comment", comment)], 0)

	def stored(self, name) -> dict:
		"""{(ref_doctype, ref_name): excluded} of the request's stored matches"""
		return {
			(m.ref_doctype, m.ref_name): m.excluded
			for m in frappe.get_doc("CRM Erasure Request", name).matches
		}

	def test_preview_warns_about_identifiers_found_on_none_of_her_records(self):
		stranger = "stranger.zz9@example.net"
		with as_user(REP):
			preview = api.log_request(
				"CRM Lead", self.lead.name, "Dana", frappe.utils.today(), [EMAIL, stranger], [PHONE]
			)
		expected = [{"kind": "Email", "position": 2}, {"kind": "Phone", "position": 1}]
		self.assertEqual(preview["identifiers_not_on_subject"], expected)
		self.assertNotIn("zz9", frappe.as_json(preview))
		frappe.db.set_value("CRM Lead", self.lead.name, "mobile_no", "(415) 555-0142", update_modified=False)
		with as_user(REP):
			again = api.get_preview(preview["name"])
		self.assertEqual(again["identifiers_not_on_subject"], [{"kind": "Email", "position": 2}])
