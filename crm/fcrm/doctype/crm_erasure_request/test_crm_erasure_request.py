# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import today

from crm.fcrm.doctype.crm_erasure_request.crm_erasure_request import (
	get_permission_query_conditions,
	has_permission,
)
from crm.privacy.setup import ensure_privacy_setup

USERS = {
	"comp1@example.com": ["Sales User", "Compliance"],
	"comp2@example.com": ["Sales User", "Compliance"],
	"salesmanager@example.com": ["Sales Manager"],
	"rep@example.com": ["Sales User"],
	"otherrep@example.com": ["Sales User"],
}


def make_user(email, roles):
	if frappe.db.exists("User", email):
		return
	frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": email.split("@")[0],
			"send_welcome_email": 0,
			"roles": [{"role": role} for role in roles],
		}
	).insert(ignore_permissions=True)


def make_request(**values):
	"""Insert a request as the current user.

	`logged_by` is forced to the session user on insert, so a requested logger is stamped
	afterwards."""
	logged_by = values.pop("logged_by", None)
	doc = frappe.get_doc(
		{"doctype": "CRM Erasure Request", "channel": "Email", "received_on": today(), **values}
	).insert(ignore_permissions=True)
	if logged_by:
		doc.db_set("logged_by", logged_by)
	return doc


class TestCRMErasureRequest(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_privacy_setup()
		for email, roles in USERS.items():
			make_user(email, roles)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.flags.in_erasure_job = False

	def test_dates_computed(self):
		r = make_request(received_on="2026-10-26")
		self.assertEqual(str(r.acknowledge_by), "2026-11-09")
		self.assertEqual(str(r.respond_by), "2026-12-10")

	def test_logged_by_is_session_user(self):
		frappe.set_user("rep@example.com")
		r = make_request()
		self.assertEqual(r.logged_by, "rep@example.com")
		self.assertEqual(r.status, "Logged")
		self.assertEqual(r.request_type, "Erasure")

	def test_cannot_close_with_open_checklist(self):
		r = make_request(
			status="Erased", checklist=[{"description": "Delete recordings at provider (Twilio)"}]
		)
		r.update({"status": "Closed", "answered_on": today(), "outcome": "Completed"})
		self.assertRaises(frappe.ValidationError, r.save)

	def test_can_close_when_checklist_done(self):
		r = make_request(
			status="Erased",
			checklist=[{"description": "Delete recordings at provider (Twilio)", "done": 1}],
		)
		r.update({"status": "Closed", "answered_on": today(), "outcome": "Completed"})
		r.save()
		self.assertEqual(r.status, "Closed")

	def test_close_needs_answered_on_and_outcome(self):
		r = make_request(status="Erased")
		r.update({"status": "Closed", "outcome": "Completed"})
		self.assertRaises(frappe.ValidationError, r.save)
		r.update({"answered_on": today(), "outcome": ""})
		self.assertRaises(frappe.ValidationError, r.save)

	def test_denied_needs_reason(self):
		r = make_request(status="Erased")
		r.update({"status": "Closed", "answered_on": today(), "outcome": "Denied"})
		self.assertRaises(frappe.ValidationError, r.save)
		r.denial_reason = "Identity could not be verified"
		r.save()
		self.assertEqual(r.status, "Closed")

	def test_declined_needs_reason(self):
		r = make_request()
		r.status = "Declined"
		self.assertRaises(frappe.ValidationError, r.save)
		r.denial_reason = "Legal exemption"
		r.save()
		self.assertEqual(r.status, "Declined")

	def test_logger_cannot_approve_even_if_compliance(self):
		r = make_request(logged_by="comp1@example.com")
		self.assertFalse(r.can_approve("comp1@example.com"))
		self.assertTrue(r.can_approve("comp2@example.com"))
		self.assertFalse(r.can_approve("salesmanager@example.com"))

	def test_visibility(self):
		r = make_request(logged_by="rep@example.com")
		self.assertTrue(has_permission(r, "read", "rep@example.com"))
		r.db_set("status", "Awaiting Sign-off")
		self.assertFalse(has_permission(r, "read", "rep@example.com"))
		self.assertTrue(has_permission(r, "read", "salesmanager@example.com"))
		self.assertTrue(has_permission(r, "read", "comp1@example.com"))
		self.assertFalse(has_permission(r, "read", "otherrep@example.com"))

	def test_other_logger_never_sees_logged_request(self):
		r = make_request(logged_by="rep@example.com")
		self.assertFalse(has_permission(r, "read", "otherrep@example.com"))

	def test_any_crm_user_can_create(self):
		doc = frappe.new_doc("CRM Erasure Request")
		self.assertTrue(has_permission(doc, "create", "rep@example.com"))
		self.assertTrue(has_permission(doc, "create", "comp1@example.com"))
		self.assertFalse(has_permission(doc, "create", "Guest"))

	def test_query_conditions_mirror_has_permission(self):
		self.assertEqual(get_permission_query_conditions("salesmanager@example.com"), "")
		self.assertEqual(get_permission_query_conditions("comp1@example.com"), "")
		self.assertEqual(get_permission_query_conditions("Administrator"), "")

		mine = make_request(logged_by="rep@example.com")
		later = make_request(logged_by="rep@example.com", status="Awaiting Sign-off")
		theirs = make_request(logged_by="otherrep@example.com")

		condition = get_permission_query_conditions("rep@example.com")
		names = frappe.db.sql_list(f"select name from `tabCRM Erasure Request` where {condition}")
		self.assertIn(mine.name, names)
		self.assertNotIn(later.name, names)
		self.assertNotIn(theirs.name, names)

	def test_checklist_tick_stamps_user(self):
		r = make_request(
			status="Erased", checklist=[{"description": "Delete recordings at provider (Twilio)"}]
		)
		frappe.set_user("comp1@example.com")
		r = frappe.get_doc("CRM Erasure Request", r.name)
		r.checklist[0].done = 1
		r.save()
		self.assertEqual(r.checklist[0].done_by, "comp1@example.com")
		self.assertTrue(r.checklist[0].done_on)

		# A later save by someone else keeps the original stamp.
		frappe.set_user("comp2@example.com")
		r = frappe.get_doc("CRM Erasure Request", r.name)
		r.contract_references = "Order 42"
		r.save()
		self.assertEqual(r.checklist[0].done_by, "comp1@example.com")

		# Unticking clears it.
		r.checklist[0].done = 0
		r.save()
		self.assertFalse(r.checklist[0].done_by)

	def test_only_compliance_changes_checklist(self):
		r = make_request(status="Erased", checklist=[{"description": "Delete recordings"}])
		frappe.set_user("salesmanager@example.com")
		r = frappe.get_doc("CRM Erasure Request", r.name)
		r.checklist[0].done = 1
		self.assertRaises(frappe.PermissionError, r.save)

		r = frappe.get_doc("CRM Erasure Request", r.name)
		r.append("checklist", {"description": "Another provider"})
		self.assertRaises(frappe.PermissionError, r.save)

		# Saving without touching the checklist is fine.
		r = frappe.get_doc("CRM Erasure Request", r.name)
		r.contract_references = "Order 42"
		r.save()

	def test_erasure_job_may_append_checklist_row(self):
		r = make_request(status="Erasing")
		frappe.set_user("salesmanager@example.com")
		frappe.flags.in_erasure_job = True
		r = frappe.get_doc("CRM Erasure Request", r.name)
		r.append("checklist", {"description": "Delete recordings at provider (Twilio)", "auto_added": 1})
		r.save(ignore_permissions=True)
		self.assertEqual(len(r.checklist), 1)
