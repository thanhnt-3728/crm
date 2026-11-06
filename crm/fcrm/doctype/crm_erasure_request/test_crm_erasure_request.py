# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import today

from crm.fcrm.doctype.crm_erasure_request.crm_erasure_request import (
	get_permission_query_conditions,
	has_permission,
)
from crm.privacy import has_compliance_role, system_write
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
	)
	# Tests set up states a user could not: insert as the system.
	with system_write():
		doc.insert(ignore_permissions=True)
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
		frappe.flags.privacy_system_write = False

	def save_as_system(self, doc):
		with system_write():
			doc.save()

	def assert_system_save_invalid(self, doc):
		"""The close/decline rules still apply to system writes."""
		with system_write(), self.assertRaises(frappe.ValidationError):
			doc.save()

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
		self.assert_system_save_invalid(r)

	def test_can_close_when_checklist_done(self):
		r = make_request(
			status="Erased",
			checklist=[{"description": "Delete recordings at provider (Twilio)", "done": 1}],
		)
		r.update({"status": "Closed", "answered_on": today(), "outcome": "Completed"})
		self.save_as_system(r)
		self.assertEqual(r.status, "Closed")

	def test_close_needs_answered_on_and_outcome(self):
		r = make_request(status="Erased")
		r.update({"status": "Closed", "outcome": "Completed"})
		self.assert_system_save_invalid(r)
		r.update({"answered_on": today(), "outcome": ""})
		self.assert_system_save_invalid(r)

	def test_denied_needs_reason(self):
		r = make_request(status="Erased")
		r.update({"status": "Closed", "answered_on": today(), "outcome": "Denied"})
		self.assert_system_save_invalid(r)
		r.denial_reason = "Identity could not be verified"
		self.save_as_system(r)
		self.assertEqual(r.status, "Closed")

	def test_declined_needs_reason(self):
		r = make_request()
		r.status = "Declined"
		self.assert_system_save_invalid(r)
		r.denial_reason = "Legal exemption"
		self.save_as_system(r)
		self.assertEqual(r.status, "Declined")

	def test_rest_write_to_status_rejected(self):
		frappe.set_user("rep@example.com")
		r = make_request()
		r.status = "Erased"
		self.assertRaises(frappe.ValidationError, r.save)

	def test_rest_write_to_protected_fields_rejected(self):
		for fieldname, value in [
			("logged_by", "comp2@example.com"),
			("approved_by", "comp2@example.com"),
			("acknowledge_by", "2030-01-01"),
			("day30_reminder_sent", 1),
		]:
			r = make_request()
			r.set(fieldname, value)
			self.assertRaises(frappe.ValidationError, r.save)

	def test_user_insert_cannot_set_system_fields(self):
		frappe.set_user("rep@example.com")
		r = frappe.get_doc(
			{
				"doctype": "CRM Erasure Request",
				"channel": "Email",
				"received_on": today(),
				"status": "Erased",
				"approved_by": "comp2@example.com",
				"approved_on": "2026-11-01 10:00:00",
				"erased_on": "2026-11-01 10:00:00",
				"delete_after": "2028-11-01",
				"day30_reminder_sent": 1,
			}
		).insert()
		self.assertEqual(r.status, "Logged")
		self.assertFalse(r.approved_by)
		self.assertFalse(r.approved_on)
		self.assertFalse(r.erased_on)
		self.assertFalse(r.delete_after)
		self.assertFalse(r.day30_reminder_sent)
		self.assertEqual(r.logged_by, "rep@example.com")

	def test_client_round_trip_is_not_a_change(self):
		r = make_request(received_on="2026-10-26")
		with system_write():
			r.approved_by = "comp2@example.com"
			r.approved_on = "2026-11-02 09:30:00"
			r.erased_on = "2026-11-02 09:31:00"
			r.delete_after = "2028-11-02"
			r.save()

		frappe.set_user("comp1@example.com")
		# What a client sends back: dates as strings, unset values as "", unticked checks as None.
		data = frappe.get_doc("CRM Erasure Request", r.name).as_dict(convert_dates_to_str=True)
		data["erasure_error"] = ""
		data["ack_reminder_sent"] = None
		data["day30_reminder_sent"] = None
		doc = frappe.get_doc(data)
		doc.save()
		self.assertEqual(str(doc.acknowledge_by), "2026-11-09")
		self.assertEqual(doc.approved_by, "comp2@example.com")

	def test_system_write_allows_status(self):
		r = make_request()
		with system_write():
			r.status = "Awaiting Sign-off"
			r.save()
		self.assertEqual(r.status, "Awaiting Sign-off")
		self.assertFalse(frappe.flags.privacy_system_write)

	def test_received_on_stays_editable_and_recomputes_deadlines(self):
		r = make_request(received_on="2026-10-26")
		r.received_on = "2026-10-27"
		r.save()
		self.assertEqual(str(r.respond_by), "2026-12-11")

	def test_logger_cannot_approve_even_if_compliance(self):
		r = make_request(logged_by="comp1@example.com")
		self.assertFalse(r.can_approve("comp1@example.com"))
		self.assertTrue(r.can_approve("comp2@example.com"))
		self.assertFalse(r.can_approve("salesmanager@example.com"))

	def test_administrator_never_approves(self):
		"""`get_roles("Administrator")` returns every role, Compliance included: approval
		reads the role assignment, and refuses the Administrator even when assigned."""
		r = make_request(logged_by="comp1@example.com")
		self.assertIn("Compliance", frappe.get_roles("Administrator"))
		self.assertFalse(has_compliance_role("Administrator"))
		self.assertFalse(r.can_approve("Administrator"))

		admin = frappe.get_doc("User", "Administrator")
		admin.append_roles("Compliance")
		admin.save(ignore_permissions=True)
		self.addCleanup(lambda: frappe.get_doc("User", "Administrator").remove_roles("Compliance"))
		self.assertTrue(has_compliance_role("Administrator"))
		self.assertFalse(r.can_approve("Administrator"))

	# -- content edits outside the approval rules --------------------------------------------

	def rest_save(self, user, name, **values):
		"""What a REST PUT or frappe.client.set_value does: load, change, save as the user."""
		frappe.set_user(user)
		doc = frappe.get_doc("CRM Erasure Request", name)
		doc.update(values)
		doc.save()
		return doc

	def test_rest_content_edit_rejected_during_erasing(self):
		lead = frappe.get_doc({"doctype": "CRM Lead", "first_name": "Someone"})
		lead.flags.ignore_mandatory = True
		lead.insert(ignore_permissions=True)
		r = make_request(
			status="Erasing",
			logged_by="rep@example.com",
			requester_names="Marisol Vega",
			identifiers=[{"kind": "Email", "value": "marisol@x.net"}],
		)
		for values in (
			{"requester_names": "Someone else"},
			{"original_message": "Changed"},
			{"contract_references": "Order 42"},
			{"identifiers": [{"kind": "Email", "value": "marisol@x.net", "excluded": 1}]},
			{
				"matches": [
					{
						"reference_doctype": "CRM Lead",
						"reference_name": lead.name,
						"confirmed": 1,
						"source": "Identifier match",
					}
				]
			},
		):
			with self.assertRaises(frappe.PermissionError, msg=str(values)):
				self.rest_save("comp1@example.com", r.name, **values)
			frappe.set_user("Administrator")
		self.assertEqual(
			frappe.db.get_value("CRM Erasure Request", r.name, "requester_names"), "Marisol Vega"
		)

	def test_rest_content_edit_allowed_within_the_approval_rules(self):
		r = make_request(logged_by="rep@example.com")
		# The logger while Logged.
		self.rest_save("rep@example.com", r.name, requester_names="Marisol Vega")
		frappe.set_user("Administrator")
		r.reload()
		with system_write():
			r.status = "Awaiting Sign-off"
			r.save()
		# Compliance until approval.
		self.rest_save("comp1@example.com", r.name, contract_references="Order 42")
		frappe.set_user("Administrator")
		self.assertEqual(
			frappe.db.get_value("CRM Erasure Request", r.name, ["requester_names", "contract_references"]),
			("Marisol Vega", "Order 42"),
		)
		# The logger, once the request has left Logged: no longer, even past the permission
		# check.
		frappe.db.set_value("CRM Erasure Request", r.name, "status", "On Hold")
		frappe.set_user("rep@example.com")
		doc = frappe.get_doc("CRM Erasure Request", r.name)
		doc.requester_names = "Changed"
		self.assertRaises(frappe.PermissionError, doc.save, ignore_permissions=True)

	def test_sales_manager_reads_but_never_writes(self):
		r = make_request(logged_by="rep@example.com", status="Awaiting Sign-off")
		self.assertTrue(has_permission(r, "read", "salesmanager@example.com"))
		self.assertFalse(has_permission(r, "write", "salesmanager@example.com"))
		self.assertTrue(has_permission(r, "write", "comp1@example.com"))
		with self.assertRaises(frappe.PermissionError):
			self.rest_save("salesmanager@example.com", r.name, original_message="Changed")

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
		r.acknowledgment_sent = 1
		r.save()
		self.assertEqual(r.checklist[0].done_by, "comp1@example.com")

		# Unticking clears it.
		r.checklist[0].done = 0
		r.save()
		self.assertFalse(r.checklist[0].done_by)

	def test_only_compliance_changes_checklist(self):
		r = make_request(status="Erased", checklist=[{"description": "Delete recordings"}])
		frappe.set_user("salesmanager@example.com")
		# Past the permission check (a code path that skips it): the checklist rule holds.
		r = frappe.get_doc("CRM Erasure Request", r.name)
		r.checklist[0].done = 1
		self.assertRaises(frappe.PermissionError, r.save, ignore_permissions=True)

		r = frappe.get_doc("CRM Erasure Request", r.name)
		r.append("checklist", {"description": "Another provider"})
		self.assertRaises(frappe.PermissionError, r.save, ignore_permissions=True)

		# Saving without touching the checklist is fine.
		r = frappe.get_doc("CRM Erasure Request", r.name)
		r.acknowledgment_sent = 1
		r.save(ignore_permissions=True)

	def test_erasure_job_may_append_checklist_row(self):
		r = make_request(status="Erasing")
		frappe.set_user("salesmanager@example.com")
		frappe.flags.in_erasure_job = True
		r = frappe.get_doc("CRM Erasure Request", r.name)
		r.append("checklist", {"description": "Delete recordings at provider (Twilio)", "auto_added": 1})
		r.save(ignore_permissions=True)
		self.assertEqual(len(r.checklist), 1)
