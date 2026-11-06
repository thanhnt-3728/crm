# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import json
import os
from unittest.mock import patch

import frappe

from crm.erasure import jobs, record_writes, verify
from crm.erasure.erasure_test_fixture_execution import (
	run_executor,
	REQUEST,
	approved_marisol_request,
	commits_recorded,
	db_values,
	her_identifier_strings,
	pending_marisol_request,
	remove_disk_file,
	write_disk_file,
)
from crm.erasure.erasure_test_fixtures import HER_IMAGE_URL, raw_insert
from crm.erasure.identifiers import Identifiers
from crm.erasure.test_executor import ExecutorCase
from crm.fcrm.doctype.crm_erasure_request.erasure_test_fixtures import REP

real_apply_fields = record_writes.apply_fields


def failing_on(doctype):
	def apply_fields(ctx, entry, name, changes, specs=None):
		if entry.doctype == doctype:
			raise frappe.db.InternalError("simulated failure")
		return real_apply_fields(ctx, entry, name, changes, specs)

	return apply_fields


class TestJobs(ExecutorCase):
	def run_job(self, name):
		with commits_recorded() as commit:
			jobs.execute_request(name)
		return commit

	def status(self, name):
		return db_values(REQUEST, name, ("status", "last_error", "outcome"))

	def test_rollback_and_retry(self):
		request = approved_marisol_request(self.fx)
		lead = db_values("CRM Lead", self.fx.lead, ("first_name", "email", "modified"))
		version_count = frappe.db.count("Version")
		with patch.object(record_writes, "apply_fields", side_effect=failing_on("Communication")):
			self.run_job(request.name)
		state = self.status(request.name)
		self.assertEqual(state["status"], "Approved")
		self.assertIn("InternalError", state["last_error"])
		self.assertIn("Communication", state["last_error"])
		self.assertFalse(any(s.lower() in state["last_error"].lower() for s in her_identifier_strings()))
		self.assertEqual(db_values("CRM Lead", self.fx.lead, lead), lead)  # the lead scrub rolled back
		self.assertEqual(frappe.db.count("Version"), version_count)

		self.run_job(request.name)  # retry
		state = self.status(request.name)
		self.assertEqual((state["status"], state["last_error"]), ("Executed", None))
		self.assertIsNone(db_values("CRM Lead", self.fx.lead, ("email",))["email"])

	def test_file_stage(self):
		paths = {
			"file_on_lead": write_disk_file("/private/files/file_on_lead.txt"),
			"shared_image": write_disk_file(HER_IMAGE_URL),
		}
		try:
			request = approved_marisol_request(self.fx)
			events = []

			def record_commit():
				status = frappe.db.get_value(REQUEST, request.name, "status")
				events.append((status, os.path.exists(paths["file_on_lead"])))

			with patch.object(frappe.db, "commit", side_effect=record_commit):
				jobs.execute_request(request.name)
			self.assertEqual(events[0], ("Executed", True))  # committed before any file went
			self.assertFalse(os.path.exists(paths["file_on_lead"]))
			self.assertTrue(os.path.exists(paths["shared_image"]))  # a colleague's File row uses it
			for label in ("file_on_lead", "file_on_email", "file_contact_image"):
				self.assertFalse(frappe.db.exists("File", self.name(label)))
			self.assertTrue(frappe.db.exists("File", self.name("file_shared_with_colleague")))
			outcome = json.loads(self.status(request.name)["outcome"])
			self.assertEqual(outcome["files_deleted"], 3)
		finally:
			for path in paths.values():
				remove_disk_file(path)

	def test_idempotent(self):
		request = approved_marisol_request(self.fx)
		self.run_job(request.name)
		executed = self.status(request.name)
		self.assertEqual(executed["status"], "Executed")
		self.assertEqual(dict(run_executor(frappe.get_doc(REQUEST, request.name)).counts), {})
		self.run_job(request.name)  # refuses: not Approved
		self.assertEqual(self.status(request.name), executed)

	def test_job_refuses_requests_that_are_not_approved(self):
		request = pending_marisol_request(self.fx)
		lead = db_values("CRM Lead", self.fx.lead, ("first_name", "email"))
		self.run_job(request.name)
		self.assertEqual(self.status(request.name)["status"], "Pending Approval")
		self.assertEqual(db_values("CRM Lead", self.fx.lead, lead), lead)

	def test_job_rechecks_the_approver(self):
		request = approved_marisol_request(self.fx)
		frappe.db.set_value(REQUEST, request.name, "approver", REP, update_modified=False)  # the requester
		lead = db_values("CRM Lead", self.fx.lead, ("first_name", "email"))
		self.run_job(request.name)
		state = self.status(request.name)
		self.assertEqual(state["status"], "Approved")
		self.assertIn("approver", state["last_error"])
		self.assertEqual(db_values("CRM Lead", self.fx.lead, lead), lead)

	def test_outcome_free_of_pii(self):
		request = approved_marisol_request(self.fx, excluded=("comm_on_lead",))
		self.run_job(request.name)
		state = self.status(request.name)
		outcome = json.loads(state["outcome"])
		self.assertEqual(set(outcome), {"changed", "docs", "files_deleted", "excluded_count", "skipped", "pending_files"})
		self.assertEqual(outcome["changed"]["CRM Lead"], 1)
		self.assertIn(self.fx.lead, outcome["docs"])
		self.assertGreaterEqual(outcome["excluded_count"], 1)
		for text in her_identifier_strings():
			self.assertNotIn(text.lower(), state["outcome"].lower())
		self.assertTrue(db_values(REQUEST, request.name, ("known_limitations",))["known_limitations"])
		request.reload()
		ids = Identifiers.from_rows(request.identifiers)
		excluded = {(m.ref_doctype, m.ref_name) for m in request.matches if m.excluded}
		self.assertEqual(verify.residual_hits(ids, excluded=excluded), [])

	def test_residual_hits_block_execution(self):
		request = approved_marisol_request(self.fx)
		lead = db_values("CRM Lead", self.fx.lead, ("first_name", "email"))

		def skip_communications(ctx, entry, name, changes, specs=None):
			if entry.doctype != "Communication":
				return real_apply_fields(ctx, entry, name, changes, specs)

		with patch.object(record_writes, "apply_fields", side_effect=skip_communications):
			self.run_job(request.name)
		state = self.status(request.name)
		self.assertEqual(state["status"], "Approved")
		self.assertIn("tabCommunication", state["last_error"])
		self.assertEqual(db_values("CRM Lead", self.fx.lead, lead), lead)

	def test_full_scan_finds_a_copy_outside_the_registry(self):
		request = approved_marisol_request(self.fx)
		ids = Identifiers.from_rows(request.identifiers)
		note = {"doctype": "Note", "title": "Erasure scan probe", "content": "mail m.reyes@example.net"}
		raw_insert(note)  # no hooks: nothing is queued for the (non-transactional) search index
		self.assertIn("tabNote", verify.full_scan(ids))
		self.assertNotIn("tabNote", verify.residual_hits(ids))
