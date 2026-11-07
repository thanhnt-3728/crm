# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Stuck jobs and leftover file bytes: the hourly reaper and sweeper (phase 05 step 8, RT-7, RT-8)."""

import json
import os
from unittest.mock import patch

import frappe
from frappe.utils import add_to_date, now_datetime

from crm.privacy.erasure import recovery
from crm.privacy.erasure.recovery import reap_stale_jobs
from crm.privacy.tests.erasure_run_case import ExecutorCase
from crm.privacy.tests.make_test_user import force_request, make_request

REASON = "Erasure job did not finish"


def ago(**delta):
	return add_to_date(now_datetime(), **{k: -v for k, v in delta.items()})


class RecoveryCase(ExecutorCase):
	def setUp(self):
		super().setUp()
		self.approve()

	def job(self):
		return self.stored("status", "erasure_job_status", "erasure_error", "approver", "approved_plan_hash")


class TestReaper(RecoveryCase):
	def test_a_job_queued_for_more_than_two_hours_is_failed(self):
		force_request(self.request, erasure_queued_at=ago(hours=3))
		reap_stale_jobs()
		job = self.job()
		self.assertEqual(
			(job.status, job.erasure_job_status, job.erasure_error), ("Awaiting sign-off", "Failed", REASON)
		)
		self.assertFalse(job.approver or job.approved_plan_hash)

	def test_a_job_queued_for_less_is_left_alone(self):
		force_request(self.request, erasure_queued_at=ago(minutes=90))
		reap_stale_jobs()
		self.assertEqual(self.job().erasure_job_status, "Queued")

	def test_a_running_job_is_failed_after_its_timeout_plus_a_quarter_hour(self):
		force_request(self.request, erasure_job_status="Running", erasure_started_at=ago(minutes=76))
		reap_stale_jobs()
		self.assertEqual(self.job().erasure_job_status, "Failed")

	def test_a_running_job_inside_that_window_is_left_alone(self):
		force_request(self.request, erasure_job_status="Running", erasure_started_at=ago(minutes=70))
		reap_stale_jobs()
		self.assertEqual(self.job().erasure_job_status, "Running")

	def test_compliance_is_told_without_any_personal_data(self):
		force_request(self.request, erasure_queued_at=ago(hours=3))
		reap_stale_jobs()
		notes = frappe.get_all("CRM Notification", {"to_user": self.compliance, "type": "Compliance",
			"notification_type_doc": self.request}, ["message"])  # fmt: skip
		self.assertTrue(any(self.request in n.message for n in notes))
		for note in notes:
			for bit in ("Marisol", "Vega", "m.vega"):
				self.assertNotIn(bit, note.message)

	def test_an_erased_request_is_never_touched(self):
		self.run_job()
		force_request(self.request, erasure_queued_at=ago(hours=9))
		reap_stale_jobs()
		self.assertEqual(self.job().status, "Erased")

	def test_the_request_can_be_approved_again_afterwards(self):
		force_request(self.request, erasure_queued_at=ago(hours=3))
		reap_stale_jobs()
		self.approve()
		self.run_job()
		self.assertEqual(self.job().status, "Erased")

	def test_one_failing_request_does_not_stop_the_others(self):
		other = make_request(
			self.manager, requester_names="Someone Else", emails=["someone.else@example.com"]
		)
		force_request(
			other, status="Awaiting sign-off", erasure_job_status="Queued", erasure_queued_at=ago(hours=3)
		)
		force_request(self.request, erasure_queued_at=ago(hours=3))
		real = recovery.fail_stale

		def first_breaks(name, *args):
			if name == self.request:
				raise RuntimeError("Marisol")
			return real(name, *args)

		with patch.object(recovery, "fail_stale", side_effect=first_breaks):
			reap_stale_jobs()
		self.assertEqual(frappe.db.get_value("CRM Erasure Request", other, "erasure_job_status"), "Failed")
		self.assertEqual(self.job().erasure_job_status, "Queued")
		logs = frappe.get_all("Error Log", {"reference_name": self.request}, ["method", "error"])
		self.assertEqual([(log.method, log.error) for log in logs], [(self.request, "RuntimeError")])


class TestSweeper(RecoveryCase):
	def leftover(self, name="leftover-sweeper-test.txt", private=1):
		path = frappe.get_site_path("private" if private else "public", "files", name)
		with open(path, "w") as handle:
			handle.write("bytes")
		self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
		url = f"/{'private/' if private else ''}files/{name}"
		return url, path

	def erased_with(self, *pending):
		force_request(
			self.request,
			status="Erased",
			erasure_job_status="",
			pending_file_deletions=json.dumps(list(pending)),
		)

	def test_bytes_still_listed_on_an_erased_request_are_deleted_and_the_list_cleared(self):
		url, path = self.leftover()
		url2, path2 = self.leftover("leftover-public-test.txt", private=0)
		self.erased_with([url, 1], [url2, 0])
		reap_stale_jobs()
		self.assertFalse(os.path.exists(path) or os.path.exists(path2))
		self.assertFalse(self.stored("pending_file_deletions").pending_file_deletions)

	def test_bytes_another_file_record_still_uses_are_kept(self):
		url, path = self.leftover()
		row = frappe.get_doc(
			{"doctype": "File", "file_name": "leftover-sweeper-test.txt", "file_url": url, "is_private": 1}
		)
		row.name = frappe.generate_hash(length=10)
		row.set_user_and_timestamp()
		row.db_insert()  # a row that shares the bytes, without the File hooks that would dedupe or move them
		self.erased_with([url, 1])
		reap_stale_jobs()
		self.assertTrue(os.path.exists(path))
		self.assertFalse(self.stored("pending_file_deletions").pending_file_deletions)

	def test_a_path_outside_the_files_folders_is_never_deleted(self):
		secret = frappe.get_site_path("site_config.json")
		self.erased_with(["/private/files/../../site_config.json", 1], ["/files/../site_config.json", 0])
		reap_stale_jobs()
		self.assertTrue(os.path.exists(secret))

	def test_a_request_that_is_not_erased_keeps_its_list(self):
		url, path = self.leftover()
		force_request(self.request, pending_file_deletions=json.dumps([[url, 1]]))
		reap_stale_jobs()
		self.assertTrue(os.path.exists(path))


class TestScheduling(RecoveryCase):
	def test_the_reaper_is_an_hourly_job(self):
		self.assertIn(
			"crm.privacy.erasure.recovery.reap_stale_jobs", frappe.get_hooks("scheduler_events")["hourly"]
		)
