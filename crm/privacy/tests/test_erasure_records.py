import re
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from crm.fcrm.doctype.crm_deal.test_crm_deal import create_test_deal
from crm.permissions.test_org_hierarchy import make_user
from crm.privacy import erasure
from crm.privacy.api import approve_request, log_request, save_request, submit_request
from crm.privacy.erasure import run_erasure
from crm.privacy.tests.factories import MARISOL_EMAIL, make_communication, make_compliance_user, make_marisol


class TestErasureRecords(IntegrationTestCase):
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
		# open_deal (now Lost) stays unconfirmed on purpose: her contact row on it must still be anonymized
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

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def test_logger_cannot_approve_and_manager_cannot_approve(self):
		frappe.set_user("rep@example.com")
		with self.assertRaises(frappe.PermissionError):
			approve_request(self.name, self.name)
		make_user("mgr@example.com", ["Sales Manager", "System Manager"])
		frappe.set_user("mgr@example.com")
		with self.assertRaises(frappe.PermissionError):
			approve_request(self.name, self.name)

	def test_wrong_confirmation(self):
		frappe.set_user(self.officer)
		with self.assertRaises(frappe.ValidationError):
			approve_request(self.name, "PDR-9999")

	def test_records_blanked_kept_and_renamed(self):
		run_erasure(self.name, self.officer)
		lead = frappe.get_doc("CRM Lead", self.m.lead)
		self.assertEqual(
			(lead.first_name, lead.lead_name, lead.email, lead.mobile_no, lead.job_title),
			(f"Erased person {self.name}",) * 2 + ("", "", ""),
		)
		self.assertEqual(lead.status, "New")
		self.assertFalse(frappe.db.exists("Contact", self.m.contact))
		new_contact = f"Erased person {self.name}"
		self.assertEqual(frappe.db.count("Contact Email", {"parent": new_contact}), 0)
		deal = frappe.get_doc("CRM Deal", self.m.won_deal)
		self.assertEqual((deal.email, deal.mobile_no, deal.deal_value, deal.status), ("", "", 8000, "Won"))
		self.assertEqual(deal.contacts[0].contact, new_contact)
		self.assertEqual(deal.contacts[0].full_name, new_contact)
		self.assertFalse(
			frappe.db.exists("Comment", {"reference_name": new_contact, "content": ["like", "%Marisol%"]})
		)
		lost = frappe.get_doc("CRM Deal", self.m.open_deal)  # unconfirmed deal
		self.assertEqual((lost.contacts[0].full_name, lost.email), (new_contact, ""))
		self.assertEqual(frappe.db.get_value("CRM Erasure Request", self.name, "status"), "Erased")

	def test_failure_rolls_back_everything(self):
		def boom(*a):
			raise RuntimeError("x")

		with patch.object(erasure, "STEPS", [erasure.erase_records, boom]):
			run_erasure(self.name, self.officer)
		self.assertEqual(frappe.db.get_value("CRM Lead", self.m.lead, "email"), "Marisol@SierraFoothills.example")
		self.assertTrue(frappe.db.exists("Contact", self.m.contact))
		r = frappe.db.get_value("CRM Erasure Request", self.name, ["status", "erasure_status"], as_dict=True)
		self.assertEqual((r.status, r.erasure_status), ("Awaiting Sign-off", "Failed"))
		run_erasure(self.name, self.officer)  # a retry after failure succeeds
		self.assertEqual(frappe.db.get_value("CRM Erasure Request", self.name, "status"), "Erased")

	# Beyond the brief: approval paths, addresses, the no-op guarantees and error text.

	def test_approve_queues_the_job(self):
		frappe.set_user(self.officer)
		with patch("frappe.enqueue") as enqueue:
			out = approve_request(self.name, f"  {self.name} ")
		self.assertEqual(out["status"], "Awaiting Sign-off")
		self.assertEqual(out["doc"]["erasure_status"], "Queued")
		enqueue.assert_called_once_with(
			"crm.privacy.erasure.run_erasure",
			queue="long",
			job_id=f"erasure-{self.name}",
			deduplicate=True,
			enqueue_after_commit=True,
			request=self.name,
			approver=self.officer,
		)

	def test_approve_holds_when_she_is_on_an_open_deal(self):
		create_test_deal(status="Negotiation", deal_value=1, contacts=[{"contact": self.m.contact}])
		frappe.set_user(self.officer)
		out = approve_request(self.name, self.name)
		self.assertEqual(out["status"], "On Hold")
		self.assertFalse(out["doc"]["erasure_status"])

	def test_contract_references_need_a_retention_period(self):
		frappe.db.set_single_value("CRM Privacy Settings", "contract_retention_months", 0)
		frappe.set_user(self.officer)
		save_request(self.name, {"contract_references": "MSA-2025-14"})
		with self.assertRaises(frappe.ValidationError):
			approve_request(self.name, self.name)

	def test_approve_needs_awaiting_sign_off(self):
		run_erasure(self.name, self.officer)
		frappe.set_user(self.officer)
		with self.assertRaises(frappe.ValidationError):
			approve_request(self.name, self.name)

	def test_address_blanked_and_renamed_links_kept(self):
		country = frappe.db.get_value("Country", {}, "name")
		address = frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": "Marisol Vega",
				"address_type": "Personal",
				"address_line1": "12 Oak Street",
				"city": "Auburn",
				"country": country,
				"email_id": MARISOL_EMAIL,
				"links": [{"link_doctype": "Contact", "link_name": self.m.contact}],
			}
		).insert()
		run_erasure(self.name, self.officer)
		new_address = f"Erased person {self.name}"
		self.assertFalse(frappe.db.exists("Address", address.name))
		row = frappe.db.get_value(
			"Address", new_address, ["address_title", "address_line1", "city", "email_id", "address_type"], as_dict=True
		)
		self.assertEqual(
			(row.address_title, row.address_line1, row.city, row.email_id, row.address_type),
			(new_address, "", "", "", "Personal"),
		)
		link = frappe.db.get_value(
			"Dynamic Link", {"parenttype": "Address", "parent": new_address}, ["link_name", "link_title"], as_dict=True
		)
		self.assertEqual((link.link_name, link.link_title), (f"Erased person {self.name}",) * 2)
		self.assertFalse(frappe.db.exists("Comment", {"reference_doctype": "Address", "comment_type": "Edit"}))
		self.assertFalse(frappe.db.exists("Dynamic Link", {"link_title": ["like", "%Marisol%"]}))

	def test_address_shared_with_organization_survives(self):
		country = frappe.db.get_value("Country", {}, "name")
		office = frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": "Sierra Foothills Dental Group",
				"address_type": "Office",
				"address_line1": "400 Lincoln Way",
				"city": "Auburn",
				"country": country,
				"links": [{"link_doctype": "Contact", "link_name": self.m.contact}],
			}
		).insert()
		frappe.db.set_value("CRM Organization", self.m.org, "address", office.name)
		frappe.db.set_value("Contact", self.m.contact, "address", office.name)
		run_erasure(self.name, self.officer)
		self.assertEqual(frappe.db.get_value("CRM Erasure Request", self.name, "status"), "Erased")
		row = frappe.db.get_value("Address", office.name, ["address_title", "address_line1", "city"], as_dict=True)
		self.assertEqual(
			(row.address_title, row.address_line1, row.city),
			("Sierra Foothills Dental Group", "400 Lincoln Way", "Auburn"),
		)
		self.assertEqual(frappe.db.get_value("CRM Organization", self.m.org, "address"), office.name)
		self.assertFalse(frappe.db.exists("Dynamic Link", {"parenttype": "Address", "parent": office.name}))
		self.assertFalse(frappe.db.get_value("Contact", f"Erased person {self.name}", "address"))

	def test_communication_link_titles_erased(self):
		c = make_communication(
			sender="tyler@northpine.example",
			recipients=MARISOL_EMAIL,
			timeline_links=[{"link_doctype": "CRM Lead", "link_name": self.m.lead}],
		)
		before = frappe.get_all("Communication Link", {"parent": c}, ["link_doctype", "link_title"])
		self.assertIn("Contact", [row.link_doctype for row in before])  # linked by her address
		self.assertTrue(any("Marisol" in (row.link_title or "") for row in before))
		run_erasure(self.name, self.officer)
		after = frappe.get_all("Communication Link", {"parent": c}, ["link_doctype", "link_name", "link_title"])
		placeholder = f"Erased person {self.name}"
		self.assertEqual({row.link_title for row in after}, {placeholder})
		self.assertIn(("Contact", placeholder), [(row.link_doctype, row.link_name) for row in after])

	def test_listed_deal_field_blanked_only_on_deals_she_is_on(self):
		frappe.get_doc(
			{
				"doctype": "CRM Personal Field",
				"parent": "CRM Privacy Settings",
				"parenttype": "CRM Privacy Settings",
				"parentfield": "personal_fields",
				"document_type": "CRM Deal",
				"fieldname": "next_step",
			}
		).db_insert()
		removed = create_test_deal(
			status="Won", deal_value=5, organization=self.m.org, deal_owner=self.officer
		).name
		for deal in (self.m.won_deal, removed):
			frappe.db.set_value("CRM Deal", deal, "next_step", "Send Marisol the proposal")
		frappe.set_user(self.officer)
		save_request(
			self.name, {"matches": [{"reference_doctype": "CRM Deal", "reference_name": removed, "confirmed": 1}]}
		)
		frappe.set_user("Administrator")
		run_erasure(self.name, self.officer)
		self.assertEqual(frappe.db.get_value("CRM Deal", self.m.won_deal, "next_step"), "")
		self.assertEqual(frappe.db.get_value("CRM Deal", removed, "next_step"), "Send Marisol the proposal")

	def test_lead_identifiers_blanked_when_unlisted_and_report_fields_never(self):
		frappe.db.delete(
			"CRM Personal Field",
			{"parenttype": "CRM Privacy Settings", "document_type": "CRM Lead", "fieldname": ["in", ["email", "mobile_no"]]},
		)
		# A row saved before the settings were validated: status must still survive.
		frappe.get_doc(
			{
				"doctype": "CRM Personal Field",
				"parent": "CRM Privacy Settings",
				"parenttype": "CRM Privacy Settings",
				"parentfield": "personal_fields",
				"document_type": "CRM Lead",
				"fieldname": "status",
			}
		).db_insert()
		run_erasure(self.name, self.officer)
		self.assertEqual(
			frappe.db.get_value("CRM Lead", self.m.lead, ["email", "mobile_no", "status"]), ("", "", "New")
		)

	def test_compliance_logger_cannot_approve_own_request(self):
		frappe.set_user(self.officer)
		own = log_request()
		save_request(own, {"identifiers": [{"kind": "Email", "value": "someone.else@example.com"}]})
		submit_request(own)
		with self.assertRaises(frappe.PermissionError):
			approve_request(own, own)

	def test_lost_savepoint_still_marks_failed(self):
		# Simulate a deadlock: the server has rolled back and the savepoint is gone.
		frappe.db.savepoint("before_erasure")
		rollback = frappe.db.rollback
		calls = []

		def fake_rollback(*, save_point=None, chain=False):
			calls.append(save_point)
			if save_point == "erasure":
				raise RuntimeError("(1305, 'SAVEPOINT erasure does not exist')")
			# Stand-in for the full rollback, which would also undo the test's setUp.
			return rollback(save_point=save_point or "before_erasure")

		def boom(*a):
			raise RuntimeError("x")

		with (
			patch.object(erasure, "STEPS", [erasure.erase_records, boom]),
			patch.object(frappe.db, "rollback", fake_rollback),
			patch("frappe.log_error") as log_error,
		):
			run_erasure(self.name, self.officer)  # does not raise
		self.assertEqual(calls, ["erasure", None])
		r = frappe.db.get_value(
			"CRM Erasure Request", self.name, ["status", "erasure_status", "erasure_error"], as_dict=True
		)
		self.assertEqual((r.status, r.erasure_status), ("Awaiting Sign-off", "Failed"))
		self.assertIn("RuntimeError", r.erasure_error)
		self.assertEqual(frappe.db.get_value("CRM Lead", self.m.lead, "email"), MARISOL_EMAIL)
		log_error.assert_called_once()
		self.assertEqual(log_error.call_args.kwargs["title"], f"Erasure failed for {self.name}")
		self.assertEqual(log_error.call_args.kwargs["message"], r.erasure_error)

	def test_no_modified_bump_and_no_new_versions(self):
		records = (("CRM Lead", self.m.lead), ("CRM Deal", self.m.won_deal), ("CRM Deal", self.m.open_deal))
		before = {record: frappe.db.get_value(*record, "modified") for record in records}
		contact_modified = frappe.db.get_value("Contact", self.m.contact, "modified")
		versions = frappe.db.count("Version", {"ref_doctype": ["in", ["CRM Lead", "CRM Deal", "Contact", "Address"]]})
		run_erasure(self.name, self.officer)
		for record, modified in before.items():
			self.assertEqual(frappe.db.get_value(*record, "modified"), modified)
		self.assertEqual(frappe.db.get_value("Contact", f"Erased person {self.name}", "modified"), contact_modified)
		self.assertEqual(
			frappe.db.count("Version", {"ref_doctype": ["in", ["CRM Lead", "CRM Deal", "Contact", "Address"]]}),
			versions,
		)
		# the deals, their values and the organization are still there
		self.assertEqual(frappe.db.get_value("CRM Deal", self.m.won_deal, "organization"), self.m.org)

	def test_runs_in_one_transaction(self):
		statements = []
		sql = frappe.db.sql

		def spy(query, *args, **kwargs):
			statements.append(str(query))
			return sql(query, *args, **kwargs)

		with patch.object(frappe.db, "sql", spy):
			run_erasure(self.name, self.officer)
		self.assertEqual(frappe.db.get_value("CRM Erasure Request", self.name, "status"), "Erased")
		implicit = re.compile(r"^\s*(commit|begin|start|create|alter|drop|rename|truncate)\b", re.IGNORECASE)
		self.assertEqual([s for s in statements if implicit.match(s)], [])

	def test_failure_leaves_nothing_queued_for_commit(self):
		queued = len(frappe.db.after_commit)

		def boom(*a):
			raise RuntimeError("x")

		with patch.object(erasure, "STEPS", [erasure.erase_records, boom]):
			run_erasure(self.name, self.officer)
		# Only the cache clear for the request's own Failed status may follow.
		extra = list(frappe.db.after_commit._functions)[queued:]
		self.assertEqual([fn for fn in extra if "clear_document_cache" not in getattr(fn, "__qualname__", "")], [])
		events = [event for event, _message, _room in getattr(frappe.local, "_realtime_log", [])]
		self.assertNotIn("doc_rename", events)

	def test_old_contact_name_leaves_global_search_after_commit(self):
		from frappe.utils.global_search import sync_value

		old = self.m.contact
		new = f"Erased person {self.name}"
		values = {"doctype": "Contact", "content": "x", "published": 0, "title": old, "route": ""}
		# __global_search is MyISAM, outside the test transaction: clean up by hand.
		sync_value({**values, "name": old})
		try:
			run_erasure(self.name, self.officer)
			self.assertTrue(frappe.db.exists("__global_search", {"doctype": "Contact", "name": old}))
			with patch("frappe.utils.global_search.update_global_search") as reindex:
				frappe.db.after_commit.run()
			self.assertFalse(frappe.db.exists("__global_search", {"doctype": "Contact", "name": old}))
			self.assertIn(new, [call.args[0].name for call in reindex.call_args_list])
		finally:
			for name in (old, new):
				frappe.db.delete("__global_search", {"doctype": "Contact", "name": name})

	def test_failure_text_carries_no_personal_data(self):
		lead = frappe.db.get_value("CRM Lead", self.m.lead, ["lead_name", "email", "mobile_no"], as_dict=True)

		def boom(*a):
			# Built from stored values so the traceback's source line holds none of them.
			raise RuntimeError(f"cannot touch {lead.lead_name} <{lead.email}> at {lead.mobile_no}")

		with patch.object(erasure, "STEPS", [erasure.erase_records, boom]):
			run_erasure(self.name, self.officer)
		error = frappe.db.get_value("CRM Erasure Request", self.name, "erasure_error")
		self.assertIn("RuntimeError", error)
		for value in ("Marisol", "Vega", "sierrafoothills", "555-0142"):
			self.assertNotIn(value.lower(), error.lower())
