# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Server-owned fields, status moves and the frozen-while-erasing rule of CRM Erasure Request
(RT-1, RT-3), exercised through the generic endpoints a client could call."""

import json

import frappe

from crm.privacy.request_status import server_write
from crm.privacy.tests.make_test_user import RequestTestCase, make_lead, make_request

DT = "CRM Erasure Request"
MATCH = {"doctype": "CRM Erasure Match", "reference_doctype": "CRM Lead", "confirmed": 1}

SERVER_OWNED_CHANGES = {
	"status": "Awaiting sign-off",
	"approver": "Administrator",
	"approved_on": "2026-11-07 10:00:00",
	"erased_on": "2026-11-07 10:00:00",
	"erasure_job_status": "Queued",
	"erasure_error": "x",
	"approved_plan_hash": "abc",
	"erasure_queued_at": "2026-11-07 10:00:00",
	"erasure_started_at": "2026-11-07 10:00:00",
	"pending_file_deletions": "[]",
	"ack_reminder_sent": 1,
	"day30_reminder_sent": 1,
	"day40_alert_sent": 1,
	"acknowledgment_sent": 1,
	"acknowledged_on": "2026-11-07",
	"closed_on": "2026-11-07",
	"purge_after": "2026-11-07",
	"logged_by": "Administrator",
	"outcome": "Denied",
	"date_answered": "2026-11-07",
	"denial_reason": "x",
}


def payload_of(name):
	return json.loads(frappe.as_json(frappe.get_doc(DT, name)))


class GuardTestCase(RequestTestCase):
	def setUp(self):
		super().setUp()
		self.lead = make_lead()
		self.name = make_request(self.logger)
		with server_write():
			doc = frappe.get_doc(DT, self.name)
			doc.append("matches", {**MATCH, "reference_name": self.lead, "is_source": 1})
			doc.append("checklist", {"description": "Delete the files", "auto_added": 1})
			doc.append("contract_references", {"reference": "SO-0001"})
			doc.save(ignore_permissions=True)

	def assert_save_refused(self, payload):
		with self.assertRaises(frappe.ValidationError):
			frappe.client.save(payload)


class TestServerOwnedFields(GuardTestCase):
	def test_each_server_owned_field_is_refused_on_a_generic_save(self):
		for user in (self.logger, self.compliance):
			frappe.set_user(user)
			for field, value in SERVER_OWNED_CHANGES.items():
				with self.subTest(user=user, field=field):
					payload = payload_of(self.name)
					payload[field] = value
					self.assert_save_refused(payload)

	def test_child_rows_cannot_be_added_changed_or_removed(self):
		for user in (self.logger, self.compliance):
			frappe.set_user(user)
			for table, new_row in (
				("matches", {**MATCH, "reference_name": self.lead}),
				("identifiers", {"doctype": "CRM Erasure Identifier", "kind": "Email", "value": "a@b.co"}),
				("checklist", {"doctype": "CRM Erasure Checklist Item", "description": "x"}),
				("contract_references", {"doctype": "CRM Erasure Contract Reference", "reference": "x"}),
			):
				with self.subTest(user=user, added=table):
					payload = payload_of(self.name)
					payload[table].append(new_row)
					self.assert_save_refused(payload)
			for table, field, value in (
				("matches", "confirmed", 0),
				("matches", "is_source", 0),
				("checklist", "done", 1),
				("contract_references", "reference", "SO-9999"),
			):
				with self.subTest(user=user, changed=f"{table}.{field}"):
					payload = payload_of(self.name)
					payload[table][0][field] = value
					self.assert_save_refused(payload)
			for table in ("matches", "checklist", "contract_references", "identifiers"):
				with self.subTest(user=user, removed=table):
					payload = payload_of(self.name)
					payload[table] = []
					self.assert_save_refused(payload)

	def test_set_value_cannot_move_the_status(self):
		frappe.set_user(self.compliance)
		with self.assertRaises(frappe.ValidationError):
			frappe.client.set_value(DT, self.name, "status", "Awaiting sign-off")
		with self.assertRaises(frappe.ValidationError):
			frappe.client.set_value(DT, self.name, "erasure_job_status", "Queued")

	def test_an_untouched_round_trip_is_accepted(self):
		for user in (self.logger, self.compliance):
			frappe.set_user(user)
			payload = payload_of(self.name)
			payload["requester_names"] = f"Edited by {user}"
			frappe.client.save(payload)
			self.assertEqual(frappe.db.get_value(DT, self.name, "requester_names"), f"Edited by {user}")

	def test_the_intake_fields_stay_editable_for_the_logger(self):
		frappe.set_user(self.logger)
		payload = payload_of(self.name)
		payload.update(channel="Phone", original_message="Updated", date_received=frappe.utils.today())
		frappe.client.save(payload)
		self.assertEqual(frappe.db.get_value(DT, self.name, "channel"), "Phone")

	def test_server_write_lets_the_api_change_them(self):
		with server_write():
			doc = frappe.get_doc(DT, self.name)
			doc.status = "Awaiting sign-off"
			doc.matches[0].confirmed = 0
			doc.save(ignore_permissions=True)
		self.assertEqual(frappe.db.get_value(DT, self.name, "status"), "Awaiting sign-off")

	def test_a_generic_insert_ignores_a_forged_logged_by(self):
		frappe.set_user(self.logger)
		doc = frappe.client.insert(
			{
				"doctype": DT,
				"channel": "Email",
				"date_received": frappe.utils.today(),
				"logged_by": self.manager,
			}
		)
		self.assertEqual(frappe.db.get_value(DT, doc.name, "logged_by"), self.logger)

	def test_a_generic_insert_cannot_start_past_logged_or_carry_server_data(self):
		frappe.set_user(self.compliance)
		base = {"doctype": DT, "channel": "Email", "date_received": frappe.utils.today()}
		for extra in (
			{"status": "Awaiting sign-off"},
			{"status": "Erased"},
			{"approver": self.compliance},
			{"erasure_job_status": "Queued"},
			{"matches": [{**MATCH, "reference_name": self.lead}]},
			{"identifiers": [{"doctype": "CRM Erasure Identifier", "kind": "Email", "value": "a@b.co"}]},
		):
			with self.subTest(extra=list(extra)), self.assertRaises(frappe.ValidationError):
				frappe.client.insert({**base, **extra})
