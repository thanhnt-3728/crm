# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Frappe's global search and the CRM search index after an erasure (review H3)."""

from unittest.mock import MagicMock, patch

import frappe

from crm.privacy.tests.erasure_run_case import ExecutorCase, snapshot
from crm.search_sqlite import CRMSearch

GONE = "(doctype = 'Contact' and name = %(contact)s) or (doctype = 'Address' and name = %(address)s) or (doctype = 'ToDo' and name = %(todo)s) or (doctype = 'Event' and name = %(event)s)"


class SearchCase(ExecutorCase):
	def rows(self, where: str, **values):
		return frappe.db.sql(
			f"select doctype, name, content from `__global_search` where {where}", values, as_dict=True
		)

	def old_rows(self):
		todo, event = self.activity.notes.todo_lead, self.activity.misc.event
		return self.rows(GONE, contact=self.p.contact, address=self.p.address, todo=todo, event=event)


class TestGlobalSearch(SearchCase):
	def test_the_fixture_has_search_rows_for_her_records(self):
		self.assertEqual(len(self.old_rows()), 4)

	def test_rows_of_erased_or_renamed_records_are_gone_and_a_colleagues_stay(self):
		self.approve_and_run()
		for (
			row
		) in self.old_rows():  # a to-do and an event survive and are searchable again, without her words
			self.assertIn(row.doctype, ("ToDo", "Event"))
			self.assertNotIn("Marisol", row.content)
		self.assertEqual(
			self.rows(
				"doctype in ('Contact', 'Address') and name in (%(c)s, %(a)s)",
				c=self.p.contact,
				a=self.p.address,
			),
			[],
		)
		self.assertEqual(len(self.rows("doctype = 'Contact' and name = %(n)s", n=self.p.colleague)), 1)

	def test_an_item_still_queued_with_her_old_text_does_not_bring_her_back(self):
		from frappe.utils.global_search import update_global_search

		update_global_search(frappe.get_doc("Contact", self.p.contact))  # queued in Redis, not yet written
		self.approve_and_run()
		self.assertEqual(
			self.rows(
				"doctype = 'Contact' and content like '%%Marisol%%' and name = %(n)s", n=self.p.contact
			),
			[],
		)

	def test_no_global_search_content_of_her_records_holds_her_words_afterwards(self):
		self.approve_and_run()
		person = f"Erased person {self.request}"
		keys = [("Contact", person), ("Address", person)]
		keys += [("ToDo", self.activity.notes.todo_lead), ("Event", self.activity.misc.event)]
		for doctype, name in keys:
			for row in self.rows("doctype = %(d)s and name = %(n)s", d=doctype, n=name):
				for word in ("Marisol", "m.vega@", "Foothill"):
					self.assertNotIn(word, row.content, f"{doctype} {name}")

	def test_surviving_records_are_searchable_again_under_their_placeholder_after_the_commit(self):
		self.approve_and_run()
		person = f"Erased person {self.request}"
		renamed = self.rows("doctype = 'Contact' and name = %(n)s", n=person)
		self.assertEqual(len(renamed), 1)
		self.assertNotIn("Marisol", renamed[0].content)

	def test_nothing_is_deleted_from_search_before_the_commit(self):
		"""`__global_search` is MyISAM: a delete cannot be rolled back, so none may happen inside the transaction."""
		self.approve()
		seen, real = [], frappe.db.sql

		def spy(query, *args, **kwargs):
			if "__global_search" in str(query) and str(query).lstrip().lower().startswith("delete"):
				seen.append(frappe.db.get_value("CRM Erasure Request", self.request, "status"))
			return real(query, *args, **kwargs)

		with patch.object(frappe.db, "sql", spy):
			self.run_job()
		self.assertTrue(seen)
		self.assertEqual(set(seen), {"Erased"})  # every delete came after the erasure was committed

	def test_a_failed_job_leaves_every_search_row_alone(self):
		self.approve()
		before = snapshot()
		with patch("crm.privacy.erasure.executor.scrub_misc.scrub", side_effect=RuntimeError("boom")):
			self.run_job()
		self.assertEqual(snapshot()["__global_search"], before["__global_search"])
		self.assertEqual(len(self.old_rows()), 4)

	def test_the_re_sync_runs_only_after_the_commit_of_the_erasure(self):
		events = []
		spy = MagicMock(side_effect=lambda doc: events.append(("resync", doc.doctype, doc.name)))
		self.approve()
		with patch("frappe.utils.global_search.update_global_search", spy):
			self.run_job(events)
		ours = [i for i, e in enumerate(events) if e[0] == "resync" and e[1] in ("Contact", "ToDo", "Event")]
		self.assertTrue(ours, "nothing was re-synced")
		self.assertGreater(min(ours), events.index(("commit", "Erased")))


class TestCrmSearchIndex(SearchCase):
	def test_the_scrubbed_notes_comments_and_emails_are_re_indexed_after_the_commit(self):
		events = []
		self.approve()
		with (
			patch.object(CRMSearch, "is_search_enabled", return_value=True),
			patch.object(CRMSearch, "index_exists", return_value=True),
			patch.object(
				CRMSearch, "index_doc", lambda me, doctype, name: events.append(("index", doctype, name))
			),
		):
			self.run_job(events)
		committed = events.index(("commit", "Erased"))
		after = {(e[1], e[2]) for e in events[committed:] if e[0] == "index"}
		n = self.activity.notes
		self.assertIn(("FCRM Note", n.note_lead), after)
		self.assertIn(("Comment", n.comment_lead), after)
		self.assertIn(("Communication", self.activity.communications.mail_lead), after)
