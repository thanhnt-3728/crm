import json
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_months, getdate

from crm.api.dashboard import get_dashboard
from crm.permissions.test_org_hierarchy import make_user
from crm.privacy.api import log_request, save_request, submit_request
from crm.privacy import erasure
from crm.privacy.erasure import run_erasure
from crm.privacy.history import finish
from crm.privacy.identifiers import is_blocked
from crm.privacy.sweep import sweep_activities
from crm.privacy.tests.factories import make_compliance_user, make_marisol, make_note


class TestHistory(IntegrationTestCase):
	def setUp(self):
		# Error Log lives in the SQLite log database, outside the test transaction.
		log_error = patch("frappe.log_error")
		log_error.start()
		self.addCleanup(log_error.stop)
		if not frappe.db.exists("CRM Lost Reason", "Other"):
			frappe.get_doc({"doctype": "CRM Lost Reason", "lost_reason": "Other"}).insert()
		make_user("rep@example.com", ["Sales User"])
		self.m = make_marisol(owner="rep@example.com")
		self.officer = make_compliance_user()
		frappe.get_doc("CRM Deal", self.m.open_deal).update(
			{"status": "Lost", "lost_reason": "Other", "lost_notes": "x"}
		).save()
		frappe.set_user("rep@example.com")
		self.name = log_request("CRM Lead", self.m.lead)
		save_request(
			self.name,
			{
				"matches": [
					{"reference_doctype": d, "reference_name": n, "confirmed": 1}
					for d, n in [("Contact", self.m.contact), ("CRM Deal", self.m.won_deal)]
				]
			},
		)
		submit_request(self.name)
		frappe.set_user("Administrator")
		self.P = f"Erased person {self.name}"

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def _versions(self, doctype: str, name: str) -> list[dict]:
		return [
			json.loads(data)
			for data in frappe.get_all("Version", {"ref_doctype": doctype, "docname": name}, pluck="data")
		]

	# From the brief

	def test_version_history_scrubbed_status_kept(self):
		lead = frappe.get_doc("CRM Lead", self.m.lead)
		lead.update({"email": "marisol.v@sierrafoothills.example", "status": "Contacted"}).save(ignore_version=False)
		save_request(self.name, {"identifiers": [{"kind": "Email", "value": "marisol.v@sierrafoothills.example"}]})
		run_erasure(self.name, self.officer)
		data = "".join(frappe.get_all("Version", {"ref_doctype": "CRM Lead", "docname": self.m.lead}, pluck="data"))
		self.assertNotIn("sierrafoothills", data.lower())
		self.assertIn("Contacted", data)

	def test_deleted_document_copy_removed(self):
		other = frappe.get_doc(
			{"doctype": "CRM Lead", "first_name": "Dup", "email": "marisol@sierrafoothills.example"}
		).insert()
		frappe.delete_doc("CRM Lead", other.name)
		run_erasure(self.name, self.officer)
		self.assertFalse(frappe.db.exists("Deleted Document", {"deleted_name": other.name}))

	def test_do_not_contact_and_retained_contract(self):
		frappe.db.set_single_value("CRM Privacy Settings", "contract_retention_months", 84)
		frappe.db.set_value("CRM Erasure Request", self.name, "contract_references", "NP-2025-114")
		run_erasure(self.name, self.officer)
		self.assertTrue(is_blocked("Email", "MARISOL@sierrafoothills.example"))
		self.assertTrue(is_blocked("Phone", "530 555 0142"))
		rc = frappe.get_last_doc("CRM Retained Contract")
		self.assertEqual((rc.person_name, rc.contract_references), ("Marisol Vega", "NP-2025-114"))
		self.assertEqual(rc.delete_after, add_months(getdate(), 84))

	def test_dashboard_numbers_identical(self):
		frappe.set_user("Administrator")
		frm, to = "2020-01-01", "2030-12-31"
		before = get_dashboard(frm, to)
		run_erasure(self.name, self.officer)
		self.assertEqual(get_dashboard(frm, to), before)

	def test_no_personal_value_left_in_db_tables_we_control(self):
		run_erasure(self.name, self.officer)
		for dt, fields in [
			("CRM Lead", ["email", "lead_name"]),
			("CRM Deal", ["email", "lead_name"]),
			("Contact", ["full_name", "email_id"]),
			("CRM Contacts", ["full_name", "email"]),
			("Communication", ["recipients", "sender", "content"]),
			("Version", ["data"]),
			("Comment", ["content"]),
			("CRM Notification", ["notification_text", "message"]),
		]:
			for f in fields:
				self.assertFalse(frappe.db.exists(dt, {f: ["like", "%sierrafoothills.example%"]}), f"{dt}.{f}")
				self.assertFalse(frappe.db.exists(dt, {f: ["like", "%Marisol%"]}), f"{dt}.{f}")

	# Beyond the brief: deal and contact history, the controller's R17, edge cases.

	def test_deal_history_keeps_values_that_are_not_hers(self):
		deal = frappe.get_doc("CRM Deal", self.m.won_deal)
		deal.update({"first_name": "Marisol", "job_title": "Office Manager"}).save(ignore_version=False)
		deal.reload()
		deal.update({"first_name": "Dana", "deal_value": 9000}).save(ignore_version=False)
		run_erasure(self.name, self.officer)
		versions = self._versions("CRM Deal", self.m.won_deal)
		changed = [pair for v in versions for pair in v.get("changed", [])]
		first_names = [pair[1:] for pair in changed if pair[0] == "first_name"]
		self.assertIn([None, self.P], first_names)
		self.assertIn([self.P, "Dana"], first_names)  # not hers: kept
		self.assertIn(self.P, [pair[2] for pair in changed if pair[0] == "job_title"])
		# Version stores currency values formatted
		self.assertIn(["8,000.00", "9,000.00"], [pair[1:] for pair in changed if pair[0] == "deal_value"])
		self.assertNotIn("marisol", json.dumps(versions).lower())
		self.assertNotIn("office manager", json.dumps(versions).lower())

	def test_deal_history_text_quoting_her_email_replaced_row_kept(self):
		data = {"changed": [["lost_notes", None, "Sent to marisol@sierrafoothills.example"], ["status", "New", "Won"]]}
		version = self._raw_version("CRM Deal", self.m.won_deal, data)
		run_erasure(self.name, self.officer)
		stored = json.loads(frappe.db.get_value("Version", version, "data"))
		self.assertEqual(stored["changed"], [["lost_notes", None, self.P], ["status", "New", "Won"]])

	def test_contact_history_found_under_its_new_name(self):
		# Contact does not track changes by default; a site may switch it on.
		data = {
			"changed": [["designation", None, "Dentist"], ["status", "Passive", "Open"]],
			"added": [["links", {"link_doctype": "CRM Lead", "link_name": self.m.lead, "link_title": "Marisol Vega"}]],
		}
		self._raw_version("Contact", self.m.contact, data)
		run_erasure(self.name, self.officer)
		new_name = frappe.db.get_value("CRM Contacts", {"parent": self.m.won_deal}, "contact")
		self.assertNotEqual(new_name, self.m.contact)
		(version,) = self._versions("Contact", new_name)
		self.assertEqual(version["changed"], [["designation", None, self.P], ["status", "Passive", "Open"]])
		self.assertEqual(version["added"][0][1]["link_title"], self.P)
		self.assertEqual(version["added"][0][1]["link_name"], self.m.lead)

	def test_activity_history_deleted(self):
		comment = frappe.get_doc(
			{
				"doctype": "Comment",
				"comment_type": "Comment",
				"reference_doctype": "CRM Lead",
				"reference_name": self.m.lead,
				"content": "Spoke to Marisol",
			}
		).insert(ignore_permissions=True)
		task = frappe.get_doc(
			{
				"doctype": "CRM Task",
				"title": "Call Marisol",
				"reference_doctype": "CRM Lead",
				"reference_docname": self.m.lead,
			}
		).insert(ignore_permissions=True)
		rows = [
			self._raw_version("Comment", comment.name, {"changed": [["content", "Spoke", "Spoke to Marisol"]]}),
			self._raw_version("CRM Task", task.name, {"changed": [["title", "Call", "Call Marisol"]]}),
		]
		run_erasure(self.name, self.officer)
		for name in rows:
			self.assertFalse(frappe.db.exists("Version", name))

	def _raw_version(self, doctype: str, name: str, data: dict | str) -> str:
		version = frappe.get_doc(
			{
				"doctype": "Version",
				"ref_doctype": doctype,
				"docname": name,
				"data": data if isinstance(data, str) else json.dumps(data),
			}
		)
		version.db_insert()
		return version.name

	def test_unparsable_version_of_her_record_is_deleted(self):
		version = self._raw_version("CRM Lead", self.m.lead, "{not json")
		run_erasure(self.name, self.officer)
		self.assertFalse(frappe.db.exists("Version", version))

	def test_note_history_deleted(self):
		note = make_note(("CRM Lead", self.m.lead), title="Call", content="Marisol prefers mornings")
		frappe.get_doc("FCRM Note", note).update({"content": "Marisol prefers evenings"}).save(ignore_version=False)
		self.assertTrue(frappe.db.exists("Version", {"ref_doctype": "FCRM Note", "docname": note}))
		run_erasure(self.name, self.officer)
		self.assertFalse(frappe.db.exists("Version", {"ref_doctype": "FCRM Note", "docname": note}))

	def test_deleted_note_mentioning_her_is_purged(self):
		other = frappe.get_doc({"doctype": "CRM Lead", "first_name": "Unrelated"}).insert()
		note = make_note(("CRM Lead", other.name), content="Ask marisol@sierrafoothills.example for the form")
		frappe.delete_doc("FCRM Note", note)
		self.assertTrue(frappe.db.exists("Deleted Document", {"deleted_name": note}))
		run_erasure(self.name, self.officer)
		self.assertFalse(frappe.db.exists("Deleted Document", {"deleted_name": note}))

	def test_deleted_copy_of_a_planned_note_is_purged_by_name(self):
		note = make_note(("CRM Lead", self.m.lead))
		copy = frappe.get_doc(
			{"doctype": "Deleted Document", "deleted_doctype": "FCRM Note", "deleted_name": note, "data": "{}"}
		).insert(ignore_permissions=True)
		run_erasure(self.name, self.officer)
		self.assertFalse(frappe.db.exists("Deleted Document", copy.name))

	def test_deleted_lead_mentioning_her_phone_is_purged(self):
		other = frappe.get_doc({"doctype": "CRM Lead", "first_name": "Dup", "mobile_no": "530.555.0142"}).insert()
		frappe.delete_doc("CRM Lead", other.name)
		run_erasure(self.name, self.officer)
		self.assertFalse(frappe.db.exists("Deleted Document", {"deleted_name": other.name}))

	def test_unrelated_history_untouched(self):
		other = frappe.get_doc(
			{"doctype": "CRM Lead", "first_name": "Dana", "email": "dana@northpine.example"}
		).insert()
		other.update({"email": "dana.k@northpine.example"}).save(ignore_version=False)
		before = frappe.get_all("Version", {"ref_doctype": "CRM Lead", "docname": other.name}, pluck="data")
		gone = frappe.get_doc(
			{"doctype": "CRM Lead", "first_name": "Tyler", "email": "tyler@northpine.example"}
		).insert()
		frappe.delete_doc("CRM Lead", gone.name)
		run_erasure(self.name, self.officer)
		after = frappe.get_all("Version", {"ref_doctype": "CRM Lead", "docname": other.name}, pluck="data")
		self.assertTrue(before)
		self.assertEqual(after, before)
		self.assertTrue(frappe.db.exists("Deleted Document", {"deleted_name": gone.name}))

	def test_finish_is_the_last_erasure_step(self):
		self.assertEqual(erasure.STEPS, [erasure.erase_records, sweep_activities, finish])

	def test_no_retained_contract_without_references(self):
		count = frappe.db.count("CRM Retained Contract")
		run_erasure(self.name, self.officer)
		self.assertEqual(frappe.db.count("CRM Retained Contract"), count)
		self.assertEqual(frappe.db.get_value("CRM Erasure Request", self.name, "status"), "Erased")
