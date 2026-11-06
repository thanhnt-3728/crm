# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import json
from datetime import timedelta
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, getdate, today

from crm.api import erasure as api
from crm.fcrm.doctype.crm_erasure_request import crm_erasure_request as controller
from crm.fcrm.doctype.crm_erasure_request import erasure_guards
from crm.fcrm.doctype.crm_erasure_request.erasure_test_fixtures import (
	MANAGER,
	PO,
	REP,
	as_user,
	ensure_users,
	make_lead,
	make_request,
)

REQUEST = "CRM Erasure Request"
STRANGER = "stranger.erasure@example.org"


class TestErasureRequestHardening(IntegrationTestCase):
	def setUp(self):
		ensure_users()
		self.lead = make_lead("Dana")
		with as_user(REP):
			self.request = make_request("CRM Lead", self.lead.name, matches=[("CRM Lead", self.lead.name)])

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def test_plain_save_cannot_swap_identifiers_or_source(self):
		other = make_lead("Other")
		for change in ("identifier", "source"):
			doc = frappe.get_doc(REQUEST, self.request.name)
			if change == "identifier":
				doc.identifiers[0].value = STRANGER
			else:
				doc.source_docname = other.name
			with self.subTest(change=change), as_user(REP), self.assertRaises(frappe.ValidationError):
				doc.save()
		stored = frappe.get_doc(REQUEST, self.request.name)
		self.assertEqual((stored.source_docname, stored.identifiers[0].value), (self.lead.name, "dana.test@example.com"))

	def test_identifier_seam_requires_one_identifier_on_the_source(self):
		with as_user(REP), self.assertRaises(frappe.ValidationError):
			frappe.get_doc(REQUEST, self.request.name).set_identifiers([{"kind": "Email", "value": STRANGER}])

	def test_refresh_and_submit_reassert_the_source_identifier(self):
		frappe.db.set_value("CRM Erasure Identifier", self.request.identifiers[0].name, {"value": STRANGER, "normalized": STRANGER})
		with as_user(REP):
			with self.assertRaises(frappe.ValidationError):
				api.refresh_matches(self.request.name)
			with self.assertRaises(frappe.ValidationError):
				api.submit_for_approval(self.request.name)
		self.assertEqual(frappe.db.get_value(REQUEST, self.request.name, "status"), "Draft")

	def test_matches_are_not_readable_over_rest_except_for_privacy_officers(self):
		for user in (REP, MANAGER):
			with self.subTest(user=user), as_user(user):
				self.assertFalse(frappe.client.get(REQUEST, self.request.name).get("matches"))  # stripped
		with as_user(PO):
			self.assertTrue(frappe.client.get(REQUEST, self.request.name)["matches"])
		with as_user(REP):  # the requester's own seams still write them
			frappe.get_doc(REQUEST, self.request.name).set_match_exclusions([("CRM Lead", self.lead.name)])
		self.assertEqual(frappe.db.get_value("CRM Erasure Match", {"parent": self.request.name}, "excluded"), 1)

	def test_only_a_draft_can_be_deleted_and_leaves_no_identifiers_behind(self):
		with as_user(REP):
			self.request.submit_for_approval()
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc(REQUEST, self.request.name)
		self.assertTrue(frappe.db.exists(REQUEST, self.request.name))
		with as_user(REP):
			draft = make_request("CRM Lead", self.lead.name)
		frappe.delete_doc(REQUEST, draft.name)
		copies = frappe.get_all("Deleted Document", {"deleted_doctype": REQUEST, "deleted_name": draft.name}, pluck="data")
		for data in copies:
			self.assertNotIn("dana.test@example.com", data)
			self.assertNotIn("Dana Test", data)
			self.assertEqual(json.loads(data).get("identifiers"), [])

	def test_due_dates_move_only_with_received_on(self):
		dates = (self.request.ack_due, self.request.response_due)
		every_day = {getdate(today()) + timedelta(days=n) for n in range(-30, 120)}
		with patch.object(controller, "load_erasure_holidays", return_value=every_day):
			frappe.get_doc(REQUEST, self.request.name).save_system_fields(hold_reason="x")
			stored = frappe.db.get_value(REQUEST, self.request.name, ["ack_due", "response_due"])
			self.assertEqual(tuple(map(getdate, stored)), tuple(map(getdate, dates)))
			doc = frappe.get_doc(REQUEST, self.request.name)
			doc.received_on = add_days(today(), -1)
			with as_user(REP):
				doc.save()  # control: the requester moves received_on, the dates follow
		self.assertNotEqual(getdate(frappe.db.get_value(REQUEST, self.request.name, "ack_due")), getdate(dates[0]))

	def test_follow_rename_does_nothing_without_requests(self):
		with patch.object(erasure_guards, "has_requests_in", return_value=False), patch.object(
			erasure_guards, "rewrite_references"
		) as rewrite:
			erasure_guards.follow_rename(self.lead, old="a", new="b")
		rewrite.assert_not_called()
