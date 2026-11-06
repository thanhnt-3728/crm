# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
"""The manual erasure runbook, rendered from the registry so the manual path and the product agree

`render_runbook()` reads REGISTRY and KNOWN_LIMITATIONS when called; test_runbook fails when the
committed `docs/ccpa-manual-erasure-runbook.md` differs. Regenerate it with
`bench --site <site> execute crm.erasure.runbook.write_runbook`.
"""

import os

import frappe

from crm.erasure import registry as erasure_registry
from crm.erasure.registry_model import HIDDEN
from crm.erasure.runbook_closing_steps import CAPTURE_NAMES, RENAME, verification
from crm.erasure.runbook_entry_steps import REQ, entry_section

RUNBOOK_FILE = "ccpa-manual-erasure-runbook.md"
TITLE = "# CCPA manual erasure runbook"
GENERATED = (
	"<!-- Generated from crm/erasure/registry.py by crm.erasure.runbook. Do not edit by hand: run "
	"`bench --site <site> execute crm.erasure.runbook.write_runbook`. -->"
)
PREREQUISITES = f"""## Before you start

- A **System Manager** runs every step, in `bench --site <site> console` or the Desk System Console.
  The Privacy team alone cannot: the steps touch Version, Deleted Document, `__global_search`,
  Email Queue and logs.
- Take a fresh backup (`bench --site <site> backup --with-files`) and keep it access-restricted.
  Her data stays in it until it rotates out.
- Book a maintenance window: nobody edits her records while the steps run.
- **Never paste her identifiers into tickets or chat.** Type them only into the console below.
  Tickets name the request number (`{REQ}` below) and nothing else.
- Statements are MariaDB. Every search is parameterised: `%(email)s` is one of her addresses,
  `%(phone_digits)s` the national digits of one of her numbers (no country code, digits only).
- A search is loose (a longer address that contains hers also hits): open each row it returns
  and drop the ones that are not hers from `found` before you change anything.
- A step may use names found by any earlier step. Steps 1 to 4 also feed each other (a deal
  leads to its lead): run their `find(...)` lines until no new name turns up, then
  `her_names = capture_her_names()` (the rename step needs them), and only then their changes.

Start the console with this helper, then run the steps in order:

```python
import json
emails = []        # her addresses, lower-case
phone_digits = []  # her numbers, national digits only
full_names = []    # her full names, lower-case (the final check only)
found = {{}}         # doctype -> names (or "<doctype>::<name>" keys) of her rows


def names(doctype):
	return tuple(found.get(doctype, ())) or ("",)


def keys(*doctypes):
	pairs = [(d, n) for d, ns in found.items() if not doctypes or d in doctypes for n in ns]
	return tuple(n if "::" in n else f"{{d}}::{{n}}" for d, n in pairs) or ("",)


def find(doctype, sql, params=None):
	runs = [{{"email": e, "phone_digits": ""}} for e in emails]
	runs += [{{"email": "", "phone_digits": d}} for d in phone_digits]
	hits = set(found.get(doctype, ()))
	for run in runs:
		hits.update(frappe.db.sql(sql, {{**run, **(params or {{}})}}, pluck=True))
	found[doctype] = sorted(hits)
	return found[doctype]


{CAPTURE_NAMES}```
"""


def runbook_path() -> str:
	# get_app_path scrubs each part ("-" -> "_"), so the file name is joined after it
	return os.path.join(frappe.get_app_path("crm", "..", "docs"), RUNBOOK_FILE)


def render_runbook(registry=None, limitations=None) -> str:
	"""Markdown runbook for `registry` (default: REGISTRY) and `limitations` (KNOWN_LIMITATIONS)

	The defaults are read from the module at call time, so entries or limitations added since
	import are rendered.
	"""
	entries = erasure_registry.REGISTRY if registry is None else registry
	limitations = erasure_registry.KNOWN_LIMITATIONS if limitations is None else limitations
	records = [entry for entry in entries if entry.kind != HIDDEN]
	hidden = [entry for entry in entries if entry.kind == HIDDEN]
	lines = [TITLE, "", GENERATED, "", PREREQUISITES, "## Her records and activity", ""]
	for number, entry in enumerate(records, start=1):
		lines += entry_section(number, entry)
	lines += ["## Hidden copies", ""]
	for number, entry in enumerate(hidden, start=len(records) + 1):
		lines += entry_section(number, entry)
	lines += [RENAME, *verification(), "## Known limitations", "", *(f"- {item}" for item in limitations), ""]
	return "\n".join(lines)


def write_runbook(path: str | None = None) -> str:
	"""Write the rendering to `path` (default: the committed copy under docs/); returns the path"""
	path = path or runbook_path()
	with open(path, "w", encoding="utf-8", newline="\n") as handle:
		handle.write(render_runbook())
	return path
