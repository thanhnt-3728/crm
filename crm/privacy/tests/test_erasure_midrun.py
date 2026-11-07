# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Rows that arrive while the job runs (review M1): scrubbed in a second pass, or the job fails and rolls back."""

from unittest.mock import patch

import frappe

from crm.privacy.erasure import scrub_activities, scrub_misc
from crm.privacy.tests.erasure_fixture_mail import mail
from crm.privacy.tests.erasure_run_case import ExecutorCase, snapshot

NOT_FINISHED = (
	"The erasure could not be completed and nothing was erased. Approve the request again to retry."
)
OPEN_DEAL = "A deal that lists the person is still open. Approve the request again once it is closed."


class MidRunCase(ExecutorCase):
	def setUp(self):
		super().setUp()
		self.content = f"Content erased {self.request}"
		self.approve()
		self.before = snapshot()

	def late_note(self, text="She called again about the plan") -> str:
		doc = frappe.get_doc({"doctype": "FCRM Note", "title": "Late", "content": text,
			"reference_doctype": "CRM Lead", "reference_docname": self.p.lead})  # fmt: skip
		return doc.insert(ignore_permissions=True).name

	def after_step(self, module, late, times: int = 1):
		"""Patch a scrubber so that `late()` runs after the real one, mid-job, up to `times` times."""
		real, calls = module.scrub, []

		def hook(plan, ctx):
			real(plan, ctx)
			if len(calls) < times:
				calls.append(late())

		return patch.object(module, "scrub", side_effect=hook), calls

	def stored_error(self):
		return self.stored("status", "erasure_job_status", "erasure_error")

	def assertFailedCleanly(self, message):
		self.assertEqual(snapshot(), self.before)
		stored = self.stored_error()
		self.assertEqual(
			(stored.status, stored.erasure_job_status, stored.erasure_error),
			("Awaiting sign-off", "Failed", message),
		)


class TestLateArrivals(MidRunCase):
	def test_a_note_added_to_her_lead_after_the_plan_was_built_is_scrubbed(self):
		patcher, calls = self.after_step(scrub_misc, self.late_note)
		with patcher:
			self.run_job()
		self.assertEqual(self.stored("status").status, "Erased")
		note = self.values("FCRM Note", calls[0], "title", "content")
		self.assertEqual(list(note.values()), [self.content, self.content])

	def test_an_email_from_her_arriving_mid_run_is_scrubbed(self):
		late = lambda: mail(self.p, self.p.email, subject="One more thing", content="Please confirm")  # noqa: E731
		patcher, calls = self.after_step(scrub_activities, late)
		with patcher:
			self.run_job()
		self.assertEqual(self.stored("status").status, "Erased")
		row = self.values("Communication", calls[0], "subject", "sender")
		self.assertEqual(row.subject, self.content)
		self.assertEqual(row.sender, f"Erased person {self.request}")

	def test_rows_the_job_wrote_itself_are_not_late_arrivals(self):
		self.run_job()  # it adds "File erased" comments and then looks again: it must not scrub or fail on them
		self.assertEqual(self.stored("status").status, "Erased")
		erased = frappe.get_all("Comment", {"content": f"File erased {self.request}"}, pluck="name")
		self.assertTrue(erased)


class TestWhatKeepsArriving(MidRunCase):
	def test_new_rows_after_the_second_pass_fail_the_job_and_change_nothing(self):
		patcher, calls = self.after_step(scrub_activities, self.late_note, times=5)
		with patcher:
			self.run_job()
		self.assertEqual(len(calls), 2)  # the first pass and the second pass each let one in
		self.assertFailedCleanly(NOT_FINISHED)

	def test_a_deal_that_opens_mid_run_fails_the_job_and_changes_nothing(self):
		from crm.privacy.tests.make_test_user import make_deal

		late = lambda: make_deal([self.p.contact], status="Negotiation")  # noqa: E731
		patcher, _calls = self.after_step(scrub_misc, late)
		with patcher:
			self.run_job()
		self.assertFailedCleanly(OPEN_DEAL)
