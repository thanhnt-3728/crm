# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import os
import re
import tempfile

import frappe
from frappe.tests import IntegrationTestCase

from crm.erasure import runbook
from crm.erasure.discovery import installed
from crm.erasure.identifiers import Identifiers
from crm.erasure.registry import KNOWN_LIMITATIONS, REGISTRY
from crm.erasure.registry_model import CLEAR, PERSON, SCRUB, Emails, Entry, content_marker, name_marker
from crm.erasure.runbook_finder_sql import entry_select
from crm.erasure.verify import column_conditions

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
PHONE_LIKE = re.compile(r"\d[\d ().-]{6,}\d")
FAKE = Entry(
	doctype="Imaginary Source",
	kind=PERSON,
	found_by="A source added after the runbook was committed",
	action=SCRUB,
	finders=(Emails(("contact_email",)),),
	fields=(("nickname", CLEAR),),
	keep=("score",),
)


class TestRunbook(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.text = runbook.render_runbook()

	def test_committed_runbook_matches_the_registry(self):
		path = runbook.runbook_path()
		self.assertTrue(os.path.exists(path), "run `bench execute crm.erasure.runbook.write_runbook`")
		with open(path, encoding="utf-8") as handle:
			committed = handle.read()
		self.assertEqual(
			committed, self.text, "stale runbook: run `bench execute crm.erasure.runbook.write_runbook`"
		)

	def test_every_registry_source_has_a_section_in_registry_order(self):
		positions = [self.text.find(f". {entry.doctype}\n") for entry in REGISTRY]
		self.assertNotIn(-1, positions, "a registry source has no section")
		self.assertEqual(positions, sorted(positions))

	def test_sections_name_what_to_change_and_what_to_keep(self):
		for entry, section in zip(REGISTRY, _sections(self.text, REGISTRY), strict=True):
			self.assertIn(entry.found_by, section, entry.doctype)
			for field in (*entry.fieldnames, *entry.keep):
				self.assertIn(f"`{field}`", section, f"{entry.doctype}.{field}")

	def test_identifier_finders_use_parameters_never_values(self):
		self.assertIn("%(email)s", self.text)
		self.assertIn("%(phone_digits)s", self.text)
		self.assertEqual(EMAIL.findall(self.text), [])
		self.assertEqual(PHONE_LIKE.findall(self.text), [])

	def test_markers_are_the_executor_markers(self):
		self.assertIn(content_marker("<REQ>"), self.text)
		self.assertIn(name_marker("<REQ>"), self.text)

	def test_prerequisites_rename_and_verification(self):
		for phrase in (
			"System Manager",
			"backup",
			"maintenance window",
			"Never paste her identifiers into tickets or chat",
			"Desk Rename",
			"renamed from",
			"bench --site <site> execute crm.erasure.verify.full_scan_request",
			"information_schema.columns",
			"regexp_replace",
			"her_names = capture_her_names()",
			"`address_title`",
			"`tabSeries`",
			"crm.erasure.post_commit.finish_files",
			'frappe.db.delete("__global_search", {"doctype": doctype, "name": old})',
		):
			self.assertIn(phrase, self.text)
		self.assertNotIn("stand-in", self.text)

	def test_rename_runs_last_like_the_executor(self):
		last_hidden = self.text.find(f". {REGISTRY[-1].doctype}\n")
		rename, verify_step = self.text.find("## Rename records named after her"), self.text.find("## Verify")
		self.assertLess(last_hidden, rename)
		self.assertLess(rename, verify_step)

	def test_verification_runs_the_conditions_of_full_scan(self):
		ids = Identifiers.from_rows(
			[{"kind": "Email", "value": "an_n%x@example.net"}, {"kind": "Phone", "value": "+1 415 555 0100"}]
		)
		blocks = re.findall(r"```python\n(.*?)```", self.text, re.S)
		namespace = {
			"emails": sorted(ids.emails),
			"phone_digits": list(ids.search_digits),
			"full_names": ["kai q"],
		}
		exec(next(b for b in blocks if b.startswith("EMAIL_SQL")), namespace)
		exec(next(b for b in blocks if "searches = " in b).split("columns = frappe.db.sql(")[0], namespace)
		column = "`content`"
		rendered = [
			(condition.format(column="content"), values) for condition, values in namespace["searches"]
		]
		expected = [
			column_conditions(column, Identifiers(emails=ids.emails)),
			column_conditions(column, Identifiers(phones=ids.phones)),
			column_conditions(column, Identifiers(), tokens=("kai q",)),
		]
		self.assertEqual(rendered, expected)

	def test_every_known_limitation_is_listed(self):
		for limitation in KNOWN_LIMITATIONS:
			self.assertIn(f"- {limitation}", self.text)

	def test_reads_the_registry_and_limitations_at_render_time(self):
		text = runbook.render_runbook(registry=(*REGISTRY, FAKE), limitations=("A limitation added later.",))
		self.assertIn(f". {FAKE.doctype}\n", text)
		self.assertIn("`contact_email`", text)
		self.assertIn("`nickname`", text)
		self.assertIn("- A limitation added later.", text)

	def test_every_console_block_is_valid_python(self):
		blocks = re.findall(r"```python\n(.*?)```", self.text, re.S)
		self.assertGreater(len(blocks), len(REGISTRY))
		for block in blocks:
			compile(block, "<runbook>", "exec")

	def test_find_statements_run_on_this_site(self):
		params = {"email": "nobody@example.net", "phone_digits": "5550100"}
		for entry in REGISTRY:
			select = entry_select(entry)
			if not select or not installed(entry):
				continue
			sql, placeholders = select
			values = {**params, **{name: ("",) for name in placeholders}}
			self.assertEqual(frappe.db.sql(sql, values), (), entry.doctype)

	def test_write_runbook_writes_the_rendering(self):
		with tempfile.TemporaryDirectory() as folder:
			path = runbook.write_runbook(os.path.join(folder, "runbook.md"))
			with open(path, encoding="utf-8") as handle:
				self.assertEqual(handle.read(), self.text)


def _sections(text: str, registry) -> list[str]:
	starts = [text.find(f". {entry.doctype}\n") for entry in registry]
	return [text[start:end] for start, end in zip(starts, [*starts[1:], len(text)], strict=True)]
