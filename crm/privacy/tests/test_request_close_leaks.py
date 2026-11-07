# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Fix round 1 (C1, H1, H2, L4): the rows around a closed request that held her data, and an answer not yet sent."""

import frappe
from frappe.utils import global_search

from crm.privacy.erasure.recovery import sweep_files
from crm.privacy.tests.close_fixture import EMAIL, CloseTestCase, force_request

COMMUNICATION = "Communication"


class TestGlobalSearch(CloseTestCase):
	"""C1: Communication indexes subject and sender, File its name, in `__global_search` (a MyISAM table)."""

	def setUp(self):
		super().setUp()
		self.addCleanup(self.drop_search_rows)
		global_search.sync_global_search()  # the real path: inserts queued their rows, now they are in the table

	def rows(self) -> list:
		names = [self.mail, self.sent, self.file.name, self.mail_file.name]
		return frappe.db.sql(
			"select doctype, name, content from __global_search where name in %s",
			(tuple(names),),
			as_dict=True,
		)

	def drop_search_rows(self) -> None:
		global_search.sync_global_search()
		names = [self.mail, self.sent, self.file.name, self.mail_file.name]
		frappe.db.sql("delete from __global_search where name in %s", (tuple(names),))

	def holding_her_words(self) -> list:
		return [r for r in self.rows() if any(w in r.content.lower() for w in ("marisol", "vega", EMAIL))]

	def test_the_fixture_really_put_her_words_into_global_search(self):
		self.assertEqual({r.doctype for r in self.holding_her_words()}, {COMMUNICATION, "File"})

	def test_no_search_row_holds_her_words_after_close(self):
		self.close()
		self.finish_after_commit()
		self.assertEqual(self.holding_her_words(), [])
		self.assertFalse([r for r in self.rows() if r.doctype == "File"])

	def test_the_emails_are_searchable_again_by_their_placeholders(self):
		self.close()
		self.finish_after_commit()
		found = {r.name: r.content for r in self.rows() if r.doctype == COMMUNICATION}
		self.assertEqual(set(found), {self.mail, self.sent})
		self.assertIn(f"Content erased {self.request}", found[self.mail])

	def test_the_search_rows_wait_for_the_commit(self):
		self.close()
		self.assertTrue(
			self.holding_her_words(), "MyISAM cannot roll back: nothing may be deleted before the commit"
		)
		pending = frappe.db.get_value("CRM Erasure Request", self.request, "pending_file_deletions")
		self.assertIn('"search"', pending)

	def test_the_hourly_sweeper_finishes_a_closed_request_whose_worker_died(self):
		self.close()  # the after-commit step never runs
		sweep_files()
		self.assertEqual(self.holding_her_words(), [])
		self.assertFalse(self.stored("pending_file_deletions").pending_file_deletions)
		self.assertFalse(self.bytes_exist(self.file))


class TestUnsentOutcomeEmail(CloseTestCase):
	"""H1: closing must not delete an answer that has not gone out."""

	def assertNothingChanged(self, row: str) -> None:
		self.assertEqual(self.stored("status").status, "Erased")
		self.assertTrue(frappe.db.exists("Email Queue", row))
		self.assertEqual(frappe.db.get_value(COMMUNICATION, self.sent, "reference_name"), self.request)

	def test_close_is_refused_while_the_outcome_email_is_not_sent_or_sending(self):
		for status in ("Not Sent", "Sending", "Partially Sent"):
			with self.subTest(status=status):
				row = self.queue_email(status)
				with self.assertRaisesRegex(frappe.ValidationError, "still being sent"):
					self.close()
				self.assertNothingChanged(row)
				frappe.db.delete("Email Queue", {"name": row})

	def test_sent_and_failed_rows_are_deleted_with_the_close(self):
		rows = [self.queue_email("Sent"), self.queue_email("Error")]
		self.close()
		for row in rows:
			self.assertFalse(frappe.db.exists("Email Queue", row))

	def test_an_unsent_notice_about_the_request_alone_neither_blocks_nor_is_deleted(self):
		row = self.queue_email("Not Sent", communication=None)
		self.close()
		self.assertTrue(frappe.db.exists("Email Queue", row))
		self.assertEqual(self.stored("status").status, "Closed")


class TestCommentsOnTheEmails(CloseTestCase):
	"""H2: an Attachment comment on an email names the file."""

	def test_comments_on_the_requests_emails_lose_their_text_whatever_their_type(self):
		frappe.get_doc(
			{
				"doctype": "Comment",
				"comment_type": "Info",
				"reference_doctype": COMMUNICATION,
				"reference_name": self.sent,
				"content": "Marisol Vega replied",
			}
		).insert(ignore_permissions=True)
		before = frappe.get_all(
			"Comment",
			{"reference_doctype": COMMUNICATION, "reference_name": ["in", [self.mail, self.sent]]},
			pluck="content",
		)
		self.assertTrue(any("scan-from-email" in c for c in before))
		self.close()
		rows = frappe.get_all(
			"Comment",
			{"reference_doctype": COMMUNICATION, "reference_name": ["in", [self.mail, self.sent]]},
			["content", "subject"],
		)
		self.assertGreaterEqual(len(rows), 2)
		for row in rows:
			self.assertEqual(row.content, f"Content erased {self.request}")
			self.assertIn(row.subject, (None, "", f"Content erased {self.request}"))


class TestPlanHashIsCleared(CloseTestCase):
	"""L4: the approved plan's digest is not part of the log entry."""

	def test_close_clears_the_approved_plan_hash(self):
		force_request(self.request, approved_plan_hash="a" * 64)
		self.close()
		self.assertFalse(self.stored("approved_plan_hash").approved_plan_hash)


class TestCloseLocksTheRequestFirst(CloseTestCase):
	"""M1: the lock is taken before any rule is checked, and held until the commit."""

	def test_the_row_lock_comes_before_validation(self):
		events = []
		real = frappe.db.get_value

		def spy(doctype, filters=None, *args, **kwargs):
			if doctype == "CRM Erasure Request" and filters == self.request and kwargs.get("for_update"):
				events.append("lock")
			return real(doctype, filters, *args, **kwargs)

		from unittest.mock import patch

		from crm.privacy import request_close

		real_validate = request_close.validate_close

		def validate(*args, **kwargs):
			events.append("validate")
			return real_validate(*args, **kwargs)

		with (
			patch.object(frappe.db, "get_value", side_effect=spy),
			patch.object(request_close, "validate_close", side_effect=validate),
		):
			self.close()
		self.assertEqual(events[:2], ["lock", "validate"])
