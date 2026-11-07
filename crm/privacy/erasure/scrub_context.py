# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""What every scrubber shares: the plan, the placeholders, and how to write (phase 05 steps 3-9).

Scrubbers write straight to the database with `update_modified=False`: never `doc.save()`, which would write a
new Version holding the old values and fire the deal, contact and automation hooks. Nothing here commits.
"""

from dataclasses import dataclass, field

import frappe

from crm.privacy.erasure.plan import ErasurePlan
from crm.privacy.placeholders import erased_content, erased_file, erased_person


@dataclass
class ScrubContext:
	request: str
	plan: ErasurePlan
	pending_files: list = field(
		default_factory=list
	)  # [file_url, is_private] to delete after the commit (RT-8)
	pending_search: list = field(
		default_factory=list
	)  # (doctype, old name) rows of global search to purge after the commit
	renames: dict = field(
		default_factory=dict
	)  # (doctype, old name) -> new name, for the re-sync after the commit
	created: dict = field(
		default_factory=dict
	)  # kind -> names of rows the job wrote itself (not late arrivals)

	@property
	def person(self) -> str:
		return erased_person(self.request)

	@property
	def content(self) -> str:
		return erased_content(self.request)

	@property
	def file(self) -> str:
		return erased_file(self.request)


def put(doctype: str, name: str, values: dict) -> None:
	"""Write fields of one row without touching `modified` and without any hook or Version."""
	if values:
		frappe.db.set_value(doctype, name, values, update_modified=False)


def blank(*fieldnames) -> dict:
	return dict.fromkeys(fieldnames)
