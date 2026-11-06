# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import hashlib
import json
import os
from unittest.mock import patch

import frappe

from crm.erasure import jobs, post_commit, record_renames
from crm.erasure.erasure_test_fixture_base import OPEN_STATUS
from crm.erasure.erasure_test_fixture_execution import (
	REQUEST,
	approved_marisol_request,
	commits_recorded,
	db_values,
	her_identifier_strings,
	remove_disk_file,
	write_disk_file,
)
from crm.erasure.erasure_test_fixtures import HER_EMAILS, raw_insert
from crm.erasure.test_executor import ExecutorCase

SCAN_URL = f"/private/files/scan of {HER_EMAILS[0]} id.txt"


class TestJobSafety(ExecutorCase):
	def run_job(self, name):
		with commits_recorded():
			jobs.execute_request(name)
		return db_values(REQUEST, name, ("status", "last_error", "outcome"))

	def scan_file(self):
		on_lead = {"attached_to_doctype": "CRM Lead", "attached_to_name": self.fx.lead, "is_private": 1}
		raw_insert({"doctype": "File", "file_name": f"scan of {HER_EMAILS[0]} id.txt", "file_url": SCAN_URL, **on_lead})
		return write_disk_file(SCAN_URL)

	def test_file_named_with_her_email_does_not_block_the_job(self):
		path = self.scan_file()
		try:
			state = self.run_job(approved_marisol_request(self.fx).name)
			self.assertEqual((state["status"], state["last_error"]), ("Executed", None))
			self.assertFalse(frappe.db.exists("File", {"file_url": SCAN_URL}))
			self.assertFalse(os.path.exists(path))
		finally:
			remove_disk_file(path)

	def test_disk_failure_leaves_files_pending_and_finish_files_retries(self):
		path = self.scan_file()
		try:
			request = approved_marisol_request(self.fx)
			real_delete = post_commit.delete_file

			def disk_full_for_the_scan(url):
				if "scan of" in url:
					raise OSError("disk")
				real_delete(url)

			with patch.object(post_commit, "delete_file", side_effect=disk_full_for_the_scan):
				state = self.run_job(request.name)
			self.assertEqual(state["status"], "Executed")
			self.assertIn("pending", state["last_error"])
			self.assertFalse(any(s.lower() in state["last_error"].lower() for s in her_identifier_strings()))
			self.assertTrue(os.path.exists(path))
			outcome = state["outcome"]
			self.assertEqual(len(json.loads(outcome)["pending_files"]), 1)  # sha256 of the site path only
			self.assertNotIn("scan", outcome)
			self.assertFalse(any(s.lower() in outcome.lower() for s in her_identifier_strings()))
			frappe.cache.delete_keys("crm:erasure")  # nothing pending may live only in the cache
			with commits_recorded():
				result = post_commit.finish_files(request.name)
			self.assertEqual(result["files_failed"], 0)
			self.assertFalse(os.path.exists(path))
			self.assertIsNone(frappe.db.get_value(REQUEST, request.name, "last_error"))
			self.assertEqual(json.loads(frappe.db.get_value(REQUEST, request.name, "outcome"))["pending_files"], [])
		finally:
			remove_disk_file(path)

	def test_worker_death_after_commit_leaves_a_hint_and_keyed_hashes(self):
		path = self.scan_file()
		try:
			request = approved_marisol_request(self.fx)
			with patch.object(jobs, "_after_commit"):  # the worker dies right after the Executed commit
				state = self.run_job(request.name)
			self.assertEqual(state["status"], "Executed")
			self.assertIn("pending; run crm.erasure.post_commit.finish_files", state["last_error"])
			stored = json.loads(state["outcome"])["pending_files"]
			plain = hashlib.sha256(SCAN_URL.replace("/private/files/", "private/files/", 1).encode()).hexdigest()
			self.assertNotIn(plain, stored)  # keyed: a guessed file name cannot be confirmed
			with commits_recorded():
				post_commit.finish_files(request.name)
			self.assertFalse(os.path.exists(path))
			self.assertIsNone(frappe.db.get_value(REQUEST, request.name, "last_error"))
		finally:
			remove_disk_file(path)

	def test_failed_run_restores_search_rows_and_drops_queued_events(self):
		from frappe.utils.global_search import sync_global_search, update_global_search

		update_global_search(frappe.get_doc("Contact", self.fx.contact))
		sync_global_search()
		request = approved_marisol_request(self.fx)
		frappe.db.after_commit.reset()
		# fails after every hidden-copy purge, and after rename_doc queued its realtime events
		with patch.object(record_renames, "_delete_rename_comments", side_effect=frappe.db.InternalError("late")):
			state = self.run_job(request.name)
		self.assertEqual(state["status"], "Approved")
		indexed = frappe.db.sql("select 1 from `__global_search` where doctype = 'Contact' and name = %s", self.fx.contact)
		self.assertTrue(indexed)  # MyISAM: deleted by the failed run, re-indexed after the rollback
		# what the failed run queued (doc_rename naming her old name) is gone; only the error save's own
		events = [entry[0] for entry in getattr(frappe.local, "_realtime_log", [])]
		self.assertNotIn("doc_rename", events)
		self.assertNotIn("marisol", frappe.as_json(getattr(frappe.local, "_realtime_log", [])).lower())

	def test_job_rechecks_the_hold(self):
		request = approved_marisol_request(self.fx)
		frappe.db.set_value("CRM Deal", self.fx.deal_open, "status", OPEN_STATUS, update_modified=False)
		lead = db_values("CRM Lead", self.fx.lead, ("first_name", "email"))
		state = self.run_job(request.name)
		self.assertEqual(state["status"], "Approved")
		self.assertIn(self.fx.deal_open, state["last_error"])
		self.assertEqual(db_values("CRM Lead", self.fx.lead, lead), lead)

	def test_open_forms_are_told_to_reload(self):
		request = approved_marisol_request(self.fx)
		with patch.object(frappe, "publish_realtime") as publish:
			self.run_job(request.name)
		event = lambda call: call.args[0] if call.args else call.kwargs.get("event")  # noqa: E731
		updated = {(c.kwargs.get("doctype"), c.kwargs.get("docname")) for c in publish.call_args_list if event(c) == "doc_update"}
		self.assertLessEqual({("CRM Lead", self.fx.lead), ("CRM Deal", self.fx.deal_won)}, updated)
		for call in publish.call_args_list:
			if event(call) == "doc_update":
				self.assertNotIn("marisol", frappe.as_json([call.args[1:], call.kwargs]).lower())
