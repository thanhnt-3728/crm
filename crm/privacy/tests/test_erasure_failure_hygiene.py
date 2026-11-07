# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""What a failed job may leak, and what a rollback really drops (review M2, M5)."""

import sys
from unittest.mock import MagicMock, patch

import frappe

from crm.privacy.erasure import scrub_misc
from crm.privacy.tests.erasure_run_case import ExecutorCase

SECRET = "Could not find Contact: Marisol Vega (m.vega@example.com)"


class HygieneCase(ExecutorCase):
	def setUp(self):
		super().setUp()
		self.approve()

	def run_quietly(self):
		"""The job's outcome: whatever it raised (nothing, when it is well behaved)."""
		try:
			self.run_job()
		except Exception as error:
			return error

	def error_logs(self):
		return frappe.get_all("Error Log", {"reference_name": self.request}, ["method", "error"])


class TestFailureRecord(HygieneCase):
	def test_the_failure_is_recorded_outside_the_except_block(self):
		"""Sentry reads the active exception when `log_error` runs, and a chained traceback prints the original."""
		seen, real = [], frappe.log_error

		def spy(*args, **kwargs):
			seen.append(sys.exc_info()[0])
			return real(*args, **kwargs)

		with (
			patch("crm.privacy.erasure.executor.scrub_misc.scrub", side_effect=RuntimeError(SECRET)),
			patch("frappe.log_error", spy),
		):
			self.run_job()
		self.assertEqual(seen, [None])
		self.assertEqual(
			[(log.method, log.error) for log in self.error_logs()], [(self.request, "RuntimeError")]
		)

	def test_a_failure_that_cannot_be_recorded_does_not_escape_and_leaks_only_class_names(self):
		with (
			patch("crm.privacy.erasure.executor.scrub_misc.scrub", side_effect=RuntimeError(SECRET)),
			patch("crm.privacy.erasure.executor_outcomes.server_write", side_effect=ValueError(SECRET)),
		):
			raised = self.run_quietly()
		self.assertIsNone(
			raised, "the job raised, so the worker would log a chained traceback with the messages"
		)
		logs = self.error_logs()
		self.assertEqual(len(logs), 1)
		self.assertEqual(logs[0].method, self.request)
		for bit in ("Marisol", "m.vega", "Traceback"):
			self.assertNotIn(bit, logs[0].error)
		self.assertIn("RuntimeError", logs[0].error)
		self.assertIn("ValueError", logs[0].error)

	def test_the_request_is_left_running_for_the_reaper_when_the_record_cannot_be_written(self):
		with (
			patch("crm.privacy.erasure.executor.scrub_misc.scrub", side_effect=RuntimeError("x")),
			patch("crm.privacy.erasure.executor_outcomes.server_write", side_effect=ValueError("y")),
		):
			raised = self.run_quietly()
		self.assertIsNone(raised)
		self.assertEqual(self.stored("erasure_job_status").erasure_job_status, "Running")


class TestAfterCommitCallbacks(HygieneCase):
	"""A real rollback drops the callbacks registered during the job; a real commit runs them."""

	def register(self, spy):
		real = scrub_misc.scrub

		def scrub(plan, ctx):
			frappe.db.after_commit.add(spy)
			real(plan, ctx)

		return scrub

	def test_callbacks_registered_during_a_failed_job_never_run(self):
		spy = MagicMock()
		with patch("crm.privacy.erasure.executor.scrub_misc.scrub", side_effect=self.failing(spy)):
			self.run_job()
		spy.assert_not_called()

	def failing(self, spy):
		def scrub(plan, ctx):
			frappe.db.after_commit.add(spy)
			raise RuntimeError("boom")

		return scrub

	def test_callbacks_registered_during_a_good_job_run_once_after_its_commit(self):
		events, spy = [], MagicMock(side_effect=lambda: events.append(("callback", None)))
		with patch("crm.privacy.erasure.executor.scrub_misc.scrub", side_effect=self.register(spy)):
			self.run_job(events)
		spy.assert_called_once()
		self.assertGreater(events.index(("callback", None)), events.index(("commit", "Erased")))
