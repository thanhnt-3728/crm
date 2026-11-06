# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
"""Exclusions over time: hand choices survive, rows reachable only through an excluded parent follow it"""

import frappe

from crm.api import erasure as api
from crm.erasure.erasure_test_fixtures import raw_insert
from crm.erasure.match_rows import format_key
from crm.erasure.test_erasure_api import EMAIL, ErasureApiCase
from crm.fcrm.doctype.crm_erasure_request.erasure_test_fixtures import REP, as_user, make_lead


class TestErasureExclusions(ErasureApiCase):
	def setUp(self):
		super().setUp()
		on_lead = {"reference_doctype": "CRM Lead", "reference_docname": self.lead.name}
		self.task = str(raw_insert({"doctype": "CRM Task", "title": "Call", **on_lead}).name)
		on_task = {"reference_type": "CRM Task", "reference_name": self.task, "allocated_to": REP}
		self.todo1 = raw_insert({"doctype": "ToDo", "description": "a", **on_task}).name
		self.todo2 = raw_insert({"doctype": "ToDo", "description": "b", **on_task}).name
		self.name = self.log()["name"]
		self.task_key = format_key("CRM Task", self.task)
		self.todo1_key, self.todo2_key = format_key("ToDo", self.todo1), format_key("ToDo", self.todo2)

	def exclude(self, *keys):
		with as_user(REP):
			return api.set_exclusions(self.name, list(keys))

	def stored(self) -> dict:
		"""{key: (excluded, new_since_logging, reason)} of the stored matches"""
		request = frappe.get_doc("CRM Erasure Request", self.name)
		return {
			format_key(m.ref_doctype, m.ref_name): (m.excluded, m.new_since_logging, m.reason)
			for m in request.matches
		}

	def test_the_rows_used_here_are_readable_by_the_rep(self):
		listed = self.keys(self.exclude())
		self.assertTrue({self.task_key, self.todo1_key, self.todo2_key} <= listed)

	def test_a_hand_excluded_child_stays_excluded_while_its_parent_is_excluded_and_after(self):
		self.exclude(self.todo1_key)
		self.exclude(self.todo1_key, self.task_key)
		stored = self.stored()
		self.assertEqual(stored[self.task_key][0], 1)
		self.assertEqual(stored[self.todo1_key][:2], (1, 0))
		self.assertEqual(stored[self.todo2_key][:2], (1, 0))  # excluded through its parent, still listed
		self.exclude(self.todo1_key)  # the parent is included again
		stored = self.stored()
		self.assertEqual(stored[self.task_key][:2], (0, 0))
		self.assertEqual(stored[self.todo1_key][:2], (1, 0))  # the rep's own choice
		self.assertEqual(stored[self.todo2_key][:2], (0, 0))  # back to its earlier state, not "new"
		self.assertNotEqual(stored[self.todo2_key][2], "via_excluded")

	def test_rows_excluded_through_a_parent_are_marked_and_ignore_echoed_keys(self):
		preview = self.exclude(self.task_key)
		row = next(r for g in preview["groups"] for r in g["rows"] if r["key"] == self.todo2_key)
		self.assertEqual((row["excluded"], row["reason"]), (1, "via_excluded"))
		self.exclude(self.todo2_key)  # parent included again; the echoed derived key is not a hand choice
		self.assertEqual(self.stored()[self.todo2_key][:2], (0, 0))

	def test_refresh_keeps_rows_excluded_through_their_parent(self):
		self.exclude(self.task_key)
		with as_user(REP):
			api.refresh_matches(self.name)
		stored = self.stored()
		self.assertEqual(stored[self.task_key][0], 1)
		self.assertEqual(stored[self.todo2_key][0], 1)

	def test_a_row_discovery_no_longer_finds_is_never_dropped(self):
		other = make_lead("Dana2")
		frappe.db.set_value("CRM Lead", other.name, "email", EMAIL, update_modified=False)
		with as_user(REP):
			api.refresh_matches(self.name)
		key = format_key("CRM Lead", other.name)
		self.assertIn(key, self.stored())
		frappe.db.set_value(
			"CRM Lead", other.name, "email", "someone.else@example.net", update_modified=False
		)
		self.exclude(format_key("Communication", self.comm))
		self.assertEqual(self.stored()[key][0], 0)

	def test_exclusions_on_rows_the_caller_cannot_read_are_kept(self):
		comment = raw_insert(
			{
				"doctype": "Comment",
				"comment_type": "Comment",
				"reference_doctype": "CRM Lead",
				"reference_name": self.lead.name,
				"content": "x",
			}
		).name
		with as_user(REP):
			api.refresh_matches(self.name)
			self.assertFalse(frappe.has_permission("Comment", "read", doc=comment))
		row = frappe.get_all(
			"CRM Erasure Match",
			{"parent": self.name, "ref_doctype": "Comment", "ref_name": comment},
			pluck="name",
		)[0]
		frappe.db.set_value("CRM Erasure Match", row, "excluded", 1)  # a Privacy Officer's choice
		self.exclude()
		self.assertEqual(self.stored()[format_key("Comment", comment)][0], 1)
