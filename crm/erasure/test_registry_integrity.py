# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase

from crm.erasure import registry_model as model
from crm.erasure.registry import KNOWN_LIMITATIONS, PERSON_FIELDS, REGISTRY
from crm.erasure.registry import entry_for as model_entry

# The Architecture table of phase 02, in order: one place to add a source
EXPECTED_SOURCES = (
	"CRM Lead",
	"CRM Deal",
	"CRM Contacts",
	"Contact",
	"Address",
	"Dynamic Link",
	"Communication Link",
	"Communication",
	"CRM Call Log",
	"FCRM Note",
	"CRM Task",
	"WA Profile",
	"WA Message",
	"Comment",
	"ToDo",
	"CRM Notification",
	"Notification Log",
	"File",
	"Version",
	"Deleted Document",
	"__global_search",
	"Email Queue",
	"WA Log",
	"Error Log",
	"_comments",
)
FINDER_TYPES = (
	model.Ref,
	model.Link,
	model.ChildLink,
	model.Backref,
	model.ChildBackref,
	model.Emails,
	model.Phones,
	model.Text,
)


def _installed(entry) -> bool:
	return not entry.app or entry.app in frappe.get_installed_apps()


class TestRegistryIntegrity(IntegrationTestCase):
	def test_every_source_is_registered_once_in_order(self):
		self.assertEqual(tuple(entry.doctype for entry in REGISTRY), EXPECTED_SOURCES)

	def test_kinds_actions_and_treatments_are_known(self):
		for entry in REGISTRY:
			with self.subTest(doctype=entry.doctype):
				self.assertIn(entry.kind, model.KINDS)
				self.assertIn(entry.action, model.ACTIONS)
				self.assertIn(entry.shared_action or entry.action, model.ACTIONS)
				self.assertTrue(entry.found_by.strip())
				for spec in entry.fields:
					self.assertIn(spec[1], model.TREATMENTS)
				for finder in entry.finders:
					self.assertIsInstance(finder, FINDER_TYPES)

	def test_optional_app_entries_are_skipped_only_when_the_app_is_absent(self):
		skipped = [entry.doctype for entry in REGISTRY if not _installed(entry)]
		optional = {entry.doctype for entry in REGISTRY if entry.app}
		self.assertEqual(optional, {"WA Profile", "WA Message", "WA Log"})
		if "whatsapp" in frappe.get_installed_apps():
			self.assertEqual(skipped, [], "whatsapp is installed: its entries must be checked, not skipped")
		else:
			self.assertEqual(set(skipped), optional)

	def test_every_listed_field_and_column_exists(self):
		for entry in REGISTRY:
			if not _installed(entry):
				continue
			with self.subTest(doctype=entry.doctype):
				if entry.table:
					self._assert_table_entry(entry)
					continue
				self.assertTrue(frappe.db.exists("DocType", entry.doctype))
				meta = frappe.get_meta(entry.doctype)
				for fieldname in (*entry.fieldnames, *entry.keep):
					self.assertTrue(meta.has_field(fieldname), f"{entry.doctype}.{fieldname}")
				for finder in entry.finders:
					self._assert_finder_columns(entry, meta, finder)

	def test_person_fields_cover_every_scrubbed_doctype(self):
		for entry in REGISTRY:
			if entry.fields and not entry.table:
				self.assertEqual(PERSON_FIELDS[entry.doctype], frozenset(entry.fieldnames))
		self.assertIn("email", PERSON_FIELDS["CRM Deal"])
		self.assertNotIn("deal_value", PERSON_FIELDS["CRM Deal"])
		self.assertNotIn("status", PERSON_FIELDS["CRM Lead"])

	def test_targets_are_found_before_the_entries_that_need_them(self):
		position = {entry.doctype: index for index, entry in enumerate(REGISTRY)}
		subjects = {"CRM Lead", "CRM Deal", "CRM Contacts", "Contact"}  # resolved together (fixed point)
		for index, entry in enumerate(REGISTRY):
			for target in _targets(entry):
				with self.subTest(doctype=entry.doctype, target=target):
					self.assertIn(target, position)
					if not (entry.doctype in subjects and target in subjects):
						self.assertLess(position[target], index)

	def test_matching_entries_have_finders_and_never_match_by_name(self):
		for entry in REGISTRY:
			with self.subTest(doctype=entry.doctype):
				if entry.match_rows and entry.kind != model.HIDDEN:
					self.assertTrue(entry.finders)
				columns = [
					c for f in entry.finders if isinstance(f, model.Emails | model.Phones) for c in f.columns
				]
				self.assertFalse({"first_name", "last_name", "lead_name", "full_name"} & set(columns))

	def test_if_hers_treatments_name_the_column_that_decides(self):
		conditional = (model.CLEAR_IF_HERS, model.MARKER_IF_HERS)
		for entry in REGISTRY:
			for spec in entry.fields:
				if spec[1] not in conditional or not _installed(entry):
					continue
				with self.subTest(doctype=entry.doctype, field=spec[0]):
					self.assertEqual(len(spec), 3, "(field, treatment, deciding column)")
					self.assertTrue(frappe.get_meta(entry.doctype).has_field(spec[2]))
		rules = {spec[0]: spec for spec in model_entry("Comment").fields}
		self.assertEqual(rules["comment_by"][2], "comment_email")
		self.assertEqual(rules["ip_address"][2], "comment_email")
		self.assertEqual(
			{s[0]: s for s in model_entry("Communication").fields}["sender_full_name"][2], "sender"
		)

	def test_files_are_found_only_through_what_they_are_attached_to(self):
		# a Backref by file_url would also select colleagues' File rows sharing deduplicated content
		for finder in model_entry("File").finders:
			self.assertIsInstance(finder, model.Ref)
			self.assertEqual(
				(finder.doctype_column, finder.name_column), ("attached_to_doctype", "attached_to_name")
			)

	def test_markers_and_known_limitations(self):
		self.assertEqual(model.content_marker("CRM-ERQ-2026-00001"), "Content erased CRM-ERQ-2026-00001")
		self.assertEqual(model.name_marker("CRM-ERQ-2026-00001"), "Erased CRM-ERQ-2026-00001")
		self.assertGreaterEqual(len(KNOWN_LIMITATIONS), 3)
		self.assertTrue(all(isinstance(text, str) and text for text in KNOWN_LIMITATIONS))

	def _assert_table_entry(self, entry):
		if entry.table == "__global_search":
			columns = {row[0] for row in frappe.db.sql("SHOW COLUMNS FROM `__global_search`")}
			for finder in entry.finders:
				self.assertTrue(set(_columns(finder)) <= columns, entry.table)
		else:
			self.assertEqual(entry.table, "_comments")
			for doctype in model.SUBJECTS:
				self.assertTrue(frappe.db.has_column(doctype, "_comments"), doctype)

	def _assert_finder_columns(self, entry, meta, finder):
		if isinstance(finder, model.Emails | model.Phones) and finder.child_doctype:
			self.assertIn(finder.child_doctype, [df.options for df in meta.get_table_fields()])
			meta = frappe.get_meta(finder.child_doctype)
		if isinstance(finder, model.ChildLink):
			self.assertIn(finder.child_doctype, [df.options for df in meta.get_table_fields()])
			return
		if isinstance(finder, model.Backref | model.ChildBackref):
			source = frappe.get_meta(finder.source)
			if isinstance(finder, model.Backref):
				self.assertTrue(source.has_field(finder.column), f"{finder.source}.{finder.column}")
				self.assertTrue(finder.by == "name" or meta.has_field(finder.by))
			else:
				self.assertIn(finder.child_doctype, [df.options for df in source.get_table_fields()])
			return
		for column in _columns(finder):
			self.assertTrue(meta.has_field(column), f"{meta.name}.{column}")


def _columns(finder) -> tuple[str, ...]:
	if isinstance(finder, model.Ref):
		return (finder.doctype_column, finder.name_column)
	if isinstance(finder, model.Link):
		return (finder.column,)
	return tuple(getattr(finder, "columns", ()))


def _targets(entry) -> set[str]:
	targets = set()
	for finder in entry.finders:
		if isinstance(finder, model.Ref | model.ChildLink):
			targets.update(t for t in finder.targets if t != "*")
		elif isinstance(finder, model.Link):
			targets.add(finder.target)
		elif isinstance(finder, model.Backref | model.ChildBackref):
			targets.add(finder.source)
	return targets
