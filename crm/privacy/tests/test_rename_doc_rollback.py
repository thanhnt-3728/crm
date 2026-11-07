# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Phase 05 step 0 [RT-6]: the spike gate. Renaming a Contact and an Address with `rename_doc` inside the
erasure transaction must be undone by one `frappe.db.rollback()`: no link, dynamic link, version, comment,
todo or file reference may keep the new name, and nothing may commit, run DDL or enqueue on the way.

The fixture (`rename_fixture.py`) is committed first, so a rollback has something to go back to.
"""

from unittest.mock import patch

import frappe
from frappe.model.rename_doc import rename_doc

from crm.privacy.tests.rename_fixture import PLACEHOLDERS, RenameFixture, references


class TestRenameDocRollback(RenameFixture):
	def test_the_fixture_has_references_in_every_kind_of_place(self):
		places = set(self.before["contact"]) | set(self.before["address"])
		for place in (
			("CRM Contacts", "contact"),
			("Dynamic Link", "link_name"),
			("Communication Link", "link_name"),
			("Communication", "reference_name"),
			("Comment", "reference_name"),
			("ToDo", "reference_name"),
			("Contact", "address"),
			("Version", "docname"),
			("File", "attached_to_name"),
		):
			self.assertIn(place, places)

	def test_rename_rewrites_every_reference_in_the_transaction(self):
		self.rename_both()
		after = self.snapshot()
		self.assertEqual(after["exists"], [False, True, False, True])
		# every place that named the old docname now names the placeholder, and no place lost a row
		for key, doctype in (("contact", "Contact"), ("address", "Address")):
			old, new = self.names[doctype], PLACEHOLDERS[doctype]
			self.assertEqual(references(doctype, [old]), {}, f"{doctype} references left on the old name")
			renamed = {
				self.names[dt]: PLACEHOLDERS[dt] for dt in self.names
			}  # the referring row may be renamed itself
			for place, rows in self.before[key].items():  # no place lost a row
				rows = [renamed.get(row, row) for row in rows]
				if place[0] == "Comment":  # it gained the "renamed from" note
					self.assertLessEqual(set(rows), set(after[key][place]))
				else:
					self.assertEqual(sorted(after[key][place]), sorted(rows), place)
			self.assertTrue(frappe.db.exists(doctype, new))
		notes = frappe.get_all(
			"Comment",
			{
				"reference_doctype": "Contact",
				"reference_name": PLACEHOLDERS["Contact"],
				"comment_type": "Edit",
			},
			pluck="content",
		)
		self.assertEqual(len(notes), 1)  # the Info comment that names the old name: step 9 deletes it
		self.assertIn("Spike Person", notes[0])

	def test_a_failure_after_the_renames_and_one_rollback_leaves_nothing_renamed(self):
		with self.assertRaises(RuntimeError):
			self.rename_both()
			self.assertNotEqual(self.snapshot(), self.before)  # the rename did change things
			raise RuntimeError("scrub_misc failed")
		frappe.db.rollback()
		self.assertEqual(self.snapshot(), self.before)
		self.assertEqual(
			[self.names["Contact"], self.names["Address"]],
			[
				frappe.db.get_value("Contact", self.names["Contact"], "name"),
				frappe.db.get_value("Address", self.names["Address"], "name"),
			],
		)
		leftover = frappe.get_all("Comment", {"content": ["like", "%Spike Person%"], "comment_type": "Edit"})
		self.assertEqual(leftover, [])
		self.assertTrue(
			frappe.db.exists("CRM Contacts", {"parent": self.deal, "contact": self.names["Contact"]})
		)

	def test_the_control_a_committed_rename_does_persist(self):
		"""Without this the rollback test could pass on a snapshot that cannot see a rename."""
		self.rename_both()
		frappe.db.commit()
		frappe.db.rollback()
		self.assertNotEqual(self.snapshot(), self.before)
		self.assertEqual(self.snapshot()["exists"], [False, True, False, True])
		# put the names back so clean_up finds the fixture under its own names
		for doctype in ("Contact", "Address"):
			rename_doc(
				doctype,
				PLACEHOLDERS[doctype],
				self.names[doctype],
				force=True,
				ignore_permissions=True,
				show_alert=False,
				rebuild_search=False,
			)
		frappe.db.commit()

	def test_the_rename_does_not_commit_run_ddl_or_enqueue(self):
		with (
			patch.object(frappe.db, "commit", wraps=frappe.db.commit) as commit,
			patch.object(frappe.db, "sql_ddl", wraps=frappe.db.sql_ddl) as ddl,
			patch("frappe.enqueue") as enqueue,
			patch("frappe.publish_realtime") as realtime,
		):
			self.rename_both()
		commit.assert_not_called()
		ddl.assert_not_called()
		enqueue.assert_not_called()
		# the only outward effect is a realtime message held until commit
		self.assertTrue(realtime.call_args_list)
		self.assertTrue(all(c.kwargs.get("after_commit") for c in realtime.call_args_list))

	def test_default_arguments_would_enqueue_a_search_rebuild(self):
		"""Why the step passes `rebuild_search=False`: the default enqueues at once, outside the transaction."""
		with patch("frappe.enqueue") as enqueue:
			rename_doc(
				"Contact",
				self.names["Contact"],
				PLACEHOLDERS["Contact"],
				force=True,
				ignore_permissions=True,
				show_alert=False,
			)
		self.assertEqual(enqueue.call_args.args[0], "frappe.utils.global_search.rebuild_for_doctype")

	def test_realtime_held_for_commit_is_dropped_by_the_rollback(self):
		self.rename_both()
		self.assertTrue(getattr(frappe.local, "_realtime_log", None))
		frappe.db.rollback()
		self.assertFalse(getattr(frappe.local, "_realtime_log", None))

	def test_ddl_after_a_write_is_refused_by_the_framework_instead_of_committing(self):
		frappe.db.set_value("Contact", self.names["Contact"], "designation", "C")
		with self.assertRaises(frappe.database.database.ImplicitCommitError):
			frappe.db.sql("alter table `tabNote` add column zz_spike_unused int")
		frappe.db.rollback()
		self.assertEqual(frappe.db.get_value("Contact", self.names["Contact"], "designation"), "B")
