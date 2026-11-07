# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""`claim` is a compare-and-set: of two workers handed the same Queued job only the first gets it (RT-1)."""

from crm.privacy.erasure.executor_checks import claim
from crm.privacy.tests.erasure_run_case import ExecutorCase, savepoint_transactions
from crm.privacy.tests.make_test_user import force_request


class TestClaimIsACompareAndSet(ExecutorCase):
	def setUp(self):
		super().setUp()
		self.approve()

	def test_the_first_claim_wins_and_the_second_is_refused(self):
		with savepoint_transactions(self.request):
			self.assertTrue(claim(self.request))
			self.assertFalse(claim(self.request))
		stored = self.stored("erasure_job_status", "erasure_started_at", "status")
		self.assertEqual((stored.erasure_job_status, stored.status), ("Running", "Awaiting sign-off"))
		self.assertTrue(stored.erasure_started_at)

	def test_a_request_that_is_not_queued_or_not_awaiting_is_not_claimed(self):
		with savepoint_transactions(self.request):
			force_request(self.request, erasure_job_status="Failed")
			self.assertFalse(claim(self.request))
			force_request(self.request, erasure_job_status="Queued", status="Declined")
			self.assertFalse(claim(self.request))
		self.assertEqual(self.stored("erasure_job_status").erasure_job_status, "Queued")

	def test_an_unknown_request_is_not_claimed(self):
		with savepoint_transactions(self.request):
			self.assertFalse(claim("PDR-9999999"))
