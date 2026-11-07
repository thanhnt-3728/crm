# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""`rename_to_placeholder` (phase 05 step 9, RT-6): the recipe the spike proved, with its two guards."""

from unittest.mock import patch

import frappe
from frappe.model.rename_doc import rename_doc

from crm.privacy.erasure.rename_support import rename_to_placeholder
from crm.privacy.tests.rename_fixture import PLACEHOLDERS, RenameFixture, references


class TestRenameToPlaceholder(RenameFixture):
	STALE_KEY = "dynamic_link_map::Dynamic Link::link_doctype"

	def go_stale(self):
		"""The distinct-doctype list of a dynamic link column is cached for 12 hours and a raw SQL row does not
		refresh it: simulate a cache that has never seen a Contact link there."""
		frappe.cache.set_value(self.STALE_KEY, ["Address"], expires_in_sec=600)
		frappe.local.dynamic_link_map = None
		self.addCleanup(frappe.cache.delete_value, self.STALE_KEY)
		self.addCleanup(setattr, frappe.local, "dynamic_link_map", None)

	def stale_rows(self, doctype: str) -> list:
		return frappe.get_all("Dynamic Link", {"link_doctype": doctype, "link_name": self.names[doctype]})

	def test_a_stale_dynamic_link_cache_makes_a_plain_rename_miss_rows(self):
		self.go_stale()
		rename_doc(
			"Contact",
			self.names["Contact"],
			PLACEHOLDERS["Contact"],
			force=True,
			ignore_permissions=True,
			show_alert=False,
			rebuild_search=False,
		)
		self.assertTrue(self.stale_rows("Contact"), "the hazard this module guards against is gone")
		frappe.db.rollback()

	def test_the_support_function_renames_every_dynamic_link_despite_a_stale_cache(self):
		self.go_stale()
		new = rename_to_placeholder("Contact", self.names["Contact"], PLACEHOLDERS["Contact"])
		self.assertEqual(new, PLACEHOLDERS["Contact"])
		self.assertEqual(self.stale_rows("Contact"), [])
		self.assertEqual(references("Contact", [self.names["Contact"]]), {})
		self.assertTrue(frappe.db.exists("Dynamic Link", {"link_doctype": "Contact", "link_name": new}))

	def test_the_info_comment_that_names_the_old_name_is_gone(self):
		rename_to_placeholder("Contact", self.names["Contact"], PLACEHOLDERS["Contact"])
		left = frappe.get_all("Comment", {"reference_name": PLACEHOLDERS["Contact"], "comment_type": "Edit"})
		self.assertEqual(left, [])
		self.assertEqual(frappe.db.count("Comment", {"content": ["like", "%Spike Person%"]}), 0)

	def test_a_taken_placeholder_gets_a_numeric_suffix(self):
		rename_to_placeholder("Contact", self.names["Contact"], PLACEHOLDERS["Contact"])
		second = frappe.get_doc({"doctype": "Contact", "first_name": "Other", "last_name": "Person"}).insert()
		self.addCleanup(frappe.delete_doc, "Contact", second.name + "", force=True, ignore_permissions=True)
		new = rename_to_placeholder("Contact", second.name, PLACEHOLDERS["Contact"])
		self.assertEqual(new, f"{PLACEHOLDERS['Contact']}-2")
		self.assertEqual(
			rename_to_placeholder("Address", self.names["Address"], PLACEHOLDERS["Address"]),
			PLACEHOLDERS["Address"],
		)

	def test_it_commits_nothing_and_a_rollback_undoes_it(self):
		before = self.before
		with (
			patch.object(frappe.db, "commit", wraps=frappe.db.commit) as commit,
			patch("frappe.enqueue") as enqueue,
		):
			rename_to_placeholder("Contact", self.names["Contact"], PLACEHOLDERS["Contact"])
			rename_to_placeholder("Address", self.names["Address"], PLACEHOLDERS["Address"])
		commit.assert_not_called()
		enqueue.assert_not_called()
		frappe.db.rollback()
		self.assertEqual(self.snapshot(), before)
