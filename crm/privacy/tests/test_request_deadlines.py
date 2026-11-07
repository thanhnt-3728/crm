# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Deadlines computed on every save of a CRM Erasure Request (design 5.4)."""

import json
from datetime import date, timedelta

import frappe
from frappe.utils import add_days, getdate, today

from crm.privacy.tests.make_test_user import RequestTestCase, make_request

DT = "CRM Erasure Request"


def payload_of(name):
	return json.loads(frappe.as_json(frappe.get_doc(DT, name)))


class TestDeadlines(RequestTestCase):
	def test_design_example_is_computed_on_insert(self):
		name = make_request(self.logger, date_received="2026-10-26")
		self.assertEqual(frappe.db.get_value(DT, name, "acknowledge_by"), date(2026, 11, 9))
		self.assertEqual(frappe.db.get_value(DT, name, "respond_by"), date(2026, 10, 26) + timedelta(days=45))

	def test_editing_date_received_recomputes_both(self):
		name = make_request(self.logger, date_received="2026-10-26")
		frappe.set_user(self.logger)
		payload = payload_of(name)
		payload["date_received"] = "2026-10-01"
		frappe.client.save(payload)
		# Columbus Day (Oct 12) is skipped
		self.assertEqual(frappe.db.get_value(DT, name, "acknowledge_by"), date(2026, 10, 16))
		self.assertEqual(frappe.db.get_value(DT, name, "respond_by"), date(2026, 11, 15))

	def test_forged_deadlines_are_overwritten(self):
		name = make_request(self.logger, date_received="2026-10-26")
		frappe.set_user(self.logger)
		payload = payload_of(name)
		payload.update(acknowledge_by="2030-01-01", respond_by="2030-01-01")
		frappe.client.save(payload)
		self.assertEqual(frappe.db.get_value(DT, name, "respond_by"), date(2026, 12, 10))

	def test_a_future_date_received_is_refused_on_insert_and_edit(self):
		tomorrow = add_days(today(), 1)
		with self.assertRaises(frappe.ValidationError):
			make_request(self.logger, date_received=tomorrow)
		name = make_request(self.logger)
		frappe.set_user(self.logger)
		payload = payload_of(name)
		payload["date_received"] = tomorrow
		with self.assertRaises(frappe.ValidationError):
			frappe.client.save(payload)

	def test_today_is_accepted(self):
		name = make_request(self.logger, date_received=today())
		self.assertEqual(frappe.db.get_value(DT, name, "date_received"), getdate(today()))
