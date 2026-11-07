import frappe
from frappe.tests import IntegrationTestCase

from crm.permissions.test_org_hierarchy import make_user
from crm.privacy.permissions import access_level, is_compliance
from crm.privacy.tests.factories import make_compliance_user, make_marisol, make_request


class TestErasureRequest(IntegrationTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def test_naming_and_deadlines(self):
		r = make_request(date_received="2026-10-26", requester_name="M")
		self.assertRegex(r.name, r"^PDR-\d{4}$")
		self.assertEqual(str(r.acknowledge_by), "2026-11-09")
		self.assertEqual(str(r.respond_by), "2026-12-10")
		self.assertEqual(r.logged_by, "Administrator")

	def test_identifiers_normalized_and_deduped(self):
		r = make_request(
			identifiers=[
				{"kind": "Phone", "value": "(530) 555-0142"},
				{"kind": "Phone", "value": "530.555.0142"},
				{"kind": "Email", "value": " A@B.example"},
			]
		)
		self.assertEqual(
			[(i.kind, i.value) for i in r.identifiers],
			[("Phone", "+15305550142"), ("Email", "a@b.example")],
		)

	def test_invalid_identifier_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			make_request(identifiers=[{"kind": "Phone", "value": "not a number"}])

	def test_future_date_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			make_request(date_received=frappe.utils.add_days(frappe.utils.today(), 1))

	def test_checklist_stamp(self):
		r = make_request(checklist=[{"description": "Delete recordings at provider (Twilio)"}])
		self.assertIsNone(r.checklist[0].done_by)
		r.checklist[0].done = 1
		r.save()
		self.assertEqual(r.checklist[0].done_by, "Administrator")
		self.assertIsNotNone(r.checklist[0].done_on)

		stamped_on = r.checklist[0].done_on
		r.save()
		self.assertEqual(r.checklist[0].done_on, stamped_on)

		r.checklist[0].done = 0
		r.save()
		self.assertFalse(r.checklist[0].done_by)
		self.assertFalse(r.checklist[0].done_on)

	def test_visibility(self):
		make_user("rep@example.com", ["Sales User"])
		make_user("other@example.com", ["Sales User"])
		make_user("mgr@example.com", ["Sales Manager"])
		officer = make_compliance_user()
		frappe.set_user("rep@example.com")
		r = make_request(requester_name="M")
		self.assertEqual(access_level(r, "rep@example.com"), "full")
		self.assertIsNone(access_level(r, "other@example.com"))
		self.assertFalse(frappe.has_permission("CRM Erasure Request", "read", r.name, user="other@example.com"))
		frappe.db.set_value("CRM Erasure Request", r.name, "status", "Awaiting Sign-off")
		r.reload()
		self.assertEqual(access_level(r, "rep@example.com"), "summary")
		self.assertFalse(frappe.has_permission("CRM Erasure Request", "read", r.name, user="rep@example.com"))
		self.assertEqual(access_level(r, "mgr@example.com"), "full")
		self.assertFalse(frappe.has_permission("CRM Erasure Request", "write", r.name, user="mgr@example.com"))
		self.assertEqual(access_level(r, officer), "full")

	def test_has_permission_matrix(self):
		make_user("rep2@example.com", ["Sales User"])
		make_user("mgr2@example.com", ["Sales Manager"])
		officer = make_compliance_user()
		frappe.set_user("rep2@example.com")
		r = make_request()
		frappe.set_user("Administrator")
		check = lambda ptype, user: frappe.has_permission("CRM Erasure Request", ptype, r.name, user=user)
		self.assertTrue(check("read", "rep2@example.com"))
		self.assertTrue(check("write", "rep2@example.com"))
		self.assertTrue(check("read", "mgr2@example.com"))
		self.assertFalse(check("write", "mgr2@example.com"))
		self.assertTrue(check("read", officer))
		self.assertTrue(check("write", officer))
		self.assertTrue(frappe.has_permission("CRM Erasure Request", "create", user="rep2@example.com"))
		self.assertTrue(frappe.has_permission("CRM Erasure Request", "create", user=officer))
		self.assertFalse(frappe.has_permission("CRM Erasure Request", "create", user="mgr2@example.com"))

	def test_sales_manager_and_system_manager_are_not_compliance(self):
		make_user("mgr3@example.com", ["Sales Manager", "System Manager"])
		self.assertFalse(is_compliance("mgr3@example.com"))
		self.assertTrue(is_compliance(make_compliance_user()))

	def test_list_query_scoped_to_logger_while_logged(self):
		make_user("rep4@example.com", ["Sales User"])
		make_user("other4@example.com", ["Sales User"])
		frappe.set_user("rep4@example.com")
		r = make_request()
		frappe.set_user("rep4@example.com")
		self.assertIn(r.name, frappe.get_list("CRM Erasure Request", pluck="name"))
		frappe.set_user("other4@example.com")
		self.assertNotIn(r.name, frappe.get_list("CRM Erasure Request", pluck="name"))
		frappe.set_user("Administrator")
		frappe.db.set_value("CRM Erasure Request", r.name, "status", "Erased")
		frappe.set_user("rep4@example.com")
		self.assertNotIn(r.name, frappe.get_list("CRM Erasure Request", pluck="name"))

	def test_marisol_factory(self):
		make_user("rep5@example.com", ["Sales User"])
		m = make_marisol(owner="rep5@example.com")
		self.assertEqual(frappe.db.get_value("CRM Deal", m.open_deal, "status"), "Negotiation")
		self.assertEqual(frappe.db.get_value("CRM Deal", m.won_deal, "status"), "Won")
		self.assertTrue(frappe.has_permission("CRM Lead", "read", m.lead, user="rep5@example.com"))
		self.assertTrue(frappe.has_permission("CRM Deal", "read", m.open_deal, user="rep5@example.com"))
		self.assertTrue(frappe.has_permission("CRM Deal", "read", m.won_deal, user="rep5@example.com"))


class TestErasureRequestWriteRules(IntegrationTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def _logger_request(self, email="logger@example.com"):
		make_user(email, ["Sales User"])
		frappe.set_user(email)
		return make_request(requester_name="M")

	def test_logger_cannot_add_checklist_row(self):
		r = self._logger_request()
		r.append("checklist", {"description": "Delete recordings", "done": 1})
		with self.assertRaises(frappe.PermissionError):
			r.save()

	def test_logger_cannot_set_protected_fields(self):
		for field, value in (("approved_by", "Administrator"), ("status", "Erased"), ("outcome", "Completed")):
			r = self._logger_request()
			r.set(field, value)
			with self.assertRaises(frappe.PermissionError, msg=field):
				r.save()

	def test_logger_cannot_set_protected_field_on_insert(self):
		make_user("insert@example.com", ["Sales User"])
		frappe.set_user("insert@example.com")
		with self.assertRaises(frappe.PermissionError):
			make_request(status="Erased")

	def test_logger_cannot_change_compliance_fields_or_logger(self):
		r = self._logger_request()
		r.contract_references = "MSA-1"
		with self.assertRaises(frappe.PermissionError):
			r.save()
		r.reload()
		r.logged_by = "Administrator"
		with self.assertRaises(frappe.PermissionError):
			r.save()

	def test_logger_can_edit_intake_fields(self):
		r = self._logger_request()
		r.requester_name = "Someone Else"
		r.save()
		self.assertEqual(frappe.db.get_value("CRM Erasure Request", r.name, "requester_name"), "Someone Else")

	def test_compliance_can_tick_checklist(self):
		officer = make_compliance_user()
		r = make_request(checklist=[{"description": "Delete recordings"}])
		frappe.set_user(officer)
		r.reload()
		r.checklist[0].done = 1
		r.save()
		self.assertEqual(r.checklist[0].done_by, officer)
		self.assertIsNotNone(r.checklist[0].done_on)

	def test_system_write_flag_allows_protected_change(self):
		r = self._logger_request()
		r.approved_by = "Administrator"
		r.flags.privacy_system_write = True
		r.save()
		self.assertEqual(frappe.db.get_value("CRM Erasure Request", r.name, "approved_by"), "Administrator")

	def test_system_write_flag_allows_status_change_by_service_code(self):
		# Service code moves status as a user who may not write the new state, so it
		# also sets ignore_permissions (the permission hook sees the in-memory status).
		r = self._logger_request()
		r.status = "Awaiting Sign-off"
		r.flags.privacy_system_write = True
		r.flags.ignore_permissions = True
		r.save()
		self.assertEqual(frappe.db.get_value("CRM Erasure Request", r.name, "status"), "Awaiting Sign-off")

	def test_done_stamp_cannot_be_overwritten(self):
		r = make_request(checklist=[{"description": "Delete recordings"}])
		r.checklist[0].done = 1
		r.save()
		stamp = (r.checklist[0].done_by, r.checklist[0].done_on)
		r.checklist[0].done_by = "Guest"
		r.checklist[0].done_on = "2001-01-01 00:00:00"
		r.save()
		self.assertEqual((r.checklist[0].done_by, r.checklist[0].done_on), stamp)
