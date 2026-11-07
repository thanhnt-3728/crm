# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Submitting a request and the On Hold decision (design 5.2, RT-2, RT-14)."""

import frappe

from crm.api.erasure_requests import (
	recheck_hold,
	submit_request,
)
from crm.privacy.tests.make_test_user import (
	RequestTestCase,
	as_user,
	make_lead,
	make_person,
	make_request,
	match_rows,
)

LEAD, DEAL, CONTACT = "CRM Lead", "CRM Deal", "Contact"
PERSONAL = ("Marisol", "Vega", "m.vega", "5305550101")


def notices(to_user, **filters):
	return frappe.get_all(
		"CRM Notification",
		filters={"to_user": to_user, "type": "Compliance", **filters},
		fields=["name", "message", "notification_text", "reference_doctype", "reference_name"],
	)


class OnHoldCase(RequestTestCase):
	def setUp(self):
		super().setUp()
		self.person = make_person(owner=self.other)
		self.name = make_request(self.manager, source_doctype=CONTACT, source_name=self.person.contact)

	def submit(self, name=None):
		return as_user(self.manager, submit_request, name or self.name)

	def stored(self, name=None):
		return frappe.get_doc("CRM Erasure Request", name or self.name)


class TestSubmit(OnHoldCase):
	def test_a_person_on_an_open_deal_puts_the_request_on_hold(self):
		result = self.submit()
		self.assertEqual(result["status"], "On Hold")
		row = match_rows(self.name)[(DEAL, self.person.negotiation)]
		self.assertEqual(row.relation, "Hold deal")
		self.assertNotIn((DEAL, self.person.won), match_rows(self.name))

	def test_the_deal_owner_is_notified_once_without_personal_data(self):
		self.submit()
		(note,) = notices(self.other, reference_name=self.person.negotiation)
		self.assertEqual(note.reference_doctype, DEAL)
		for text in (note.message, note.notification_text):
			self.assertIn(self.name, text)
			self.assertIn(self.person.negotiation, text)
			for fragment in PERSONAL:
				self.assertNotIn(fragment, text)
		as_user(self.compliance, recheck_hold, self.name)
		self.assertEqual(len(notices(self.other, reference_name=self.person.negotiation)), 1)

	def test_the_owner_email_carries_the_same_text(self):
		self.submit()
		queued = frappe.get_all(
			"Email Queue",
			filters={"reference_doctype": "CRM Erasure Request", "reference_name": self.name},
			fields=["message"],
		)
		self.assertEqual(len(queued), 1)
		self.assertIn(self.person.negotiation, queued[0].message)
		for fragment in PERSONAL:
			self.assertNotIn(fragment, queued[0].message)

	def test_a_deal_without_an_owner_holds_the_request_and_notifies_nobody(self):
		frappe.db.set_value(DEAL, self.person.negotiation, "deal_owner", None)
		self.assertEqual(self.submit()["status"], "On Hold")
		self.assertEqual(frappe.get_all("CRM Notification", filters={"type": "Compliance"}), [])

	def test_nothing_open_goes_to_sign_off_and_compliance_is_told(self):
		frappe.db.set_value(DEAL, self.person.negotiation, "status", "Won")
		result = self.submit()
		self.assertEqual(result["status"], "Awaiting sign-off")
		(note,) = notices(self.compliance, reference_name=self.name)
		self.assertIn("awaits sign-off", note.notification_text)
		self.assertIn(self.name, note.notification_text)
		self.assertEqual(note.reference_doctype, "CRM Erasure Request")

	def test_the_deadlines_do_not_move(self):
		before = self.stored()
		self.submit()
		after = self.stored()
		self.assertEqual((after.respond_by, after.acknowledge_by), (before.respond_by, before.acknowledge_by))

	def test_the_logger_sees_only_status_and_dates_afterwards(self):
		lead = make_lead(owner=self.logger, first_name="Own", email="own@example.com")
		name = make_request(self.logger, source_doctype=LEAD, source_name=lead)
		result = as_user(self.logger, submit_request, name)
		self.assertEqual(set(result), {"name", "status", "acknowledge_by", "respond_by", "days_left"})
		self.assertEqual(result["status"], "Awaiting sign-off")

	def test_it_needs_a_confirmed_match(self):
		name = make_request(self.manager)
		with self.assertRaises(frappe.ValidationError):
			as_user(self.manager, submit_request, name)

	def test_it_needs_a_kept_identifier(self):
		for row in self.stored().identifiers:
			frappe.db.set_value("CRM Erasure Identifier", row.name, "excluded", 1)
		with self.assertRaises(frappe.ValidationError):
			self.submit()

	def test_it_works_on_a_logged_request_only(self):
		self.submit()
		with self.assertRaises((frappe.ValidationError, frappe.PermissionError)):
			as_user(self.compliance, submit_request, self.name)
