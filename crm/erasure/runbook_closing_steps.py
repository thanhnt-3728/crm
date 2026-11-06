# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
"""Runbook: the last steps, renaming her records (as `record_renames` does) and the residual check

The check's SQL fragments come from `verify.column_conditions`, the function the product's own
`full_scan` uses, rendered with stand-in identifiers so no value reaches the document.
"""

from crm.erasure.identifiers import _AFTER, _BEFORE, Identifiers
from crm.erasure.phone_numbers import phone_from_normalized
from crm.erasure.record_renames import NAME_SOURCES, RENAMED_DOCTYPES
from crm.erasure.registry_model import name_marker
from crm.erasure.runbook_entry_steps import REQ
from crm.erasure.verify import (
	EMAIL_ENCODINGS,
	ENCODED_BEFORE,
	REQUEST_TABLES,
	TEXT_TYPES,
	column_conditions,
)

COLUMN = "`{column}`"  # a placeholder the console's f-string fills in
STAND_IN_EMAIL = Identifiers(emails=frozenset({"stand-in@invalid"}))
STAND_IN_PHONE = Identifiers(phones=(phone_from_normalized("+12025550100"),))
MARKER = name_marker(REQ)

CAPTURE_NAMES = f"""def capture_her_names():
	\"\"\"Her names as stored before anything is changed (the rename step needs them)\"\"\"
	sources = {NAME_SOURCES!r}
	return {{v.strip() for d, f in sources for v in frappe.get_all(d, {{"name": ("in", names(d))}}, pluck=f) if v and v.strip()}}
"""

RENAME = f"""## Rename records named after her

The product does this last, after the hidden copies. Contact and Address IDs are often made of
her name ("<first> <last>", "<title>-Billing"). Rename, via Desk Rename (never merge):

- every {" and ".join(RENAMED_DOCTYPES)} in `found` that was scrubbed;
- a shared Address (only her link was removed) only when titled after her: its `address_title`
  is one of `her_names`, or its ID is one of them or starts with "<name>-". Set its
  `address_title` to `{MARKER}` first.

The new ID is `{MARKER}`, or `{MARKER}-1`, `{MARKER}-2`, ... when that is taken. Skip records
already named so. Desk refuses the rename while an erasure request for her is open in the CRM:
then run the product's job instead. After each rename, clean what the rename left behind and
replace the old ID in `found`:

```python
# doctype ("Contact" or "Address"), old and new: the IDs of one renamed record
comments = frappe.get_all("Comment", {{"reference_doctype": doctype, "reference_name": new,
	"comment_type": "Edit", "content": ("like", f"%{{old}}%")}}, pluck="name")  # "renamed from <old> to <new>"
frappe.db.delete("Version", {{"ref_doctype": "Comment", "docname": ("in", comments or [""])}})
frappe.db.delete("Comment", {{"name": ("in", comments or [""])}})


def swap(value):
	if isinstance(value, dict):
		return {{k: swap(v) for k, v in value.items()}}
	if isinstance(value, list):
		return [swap(v) for v in value]
	return new if value == old else value


for version, data in frappe.db.sql("select name, data from `tabVersion` where data like %s", (f"%{{old}}%",)):
	fixed = swap(json.loads(data or "{{}}"))
	if fixed != json.loads(data or "{{}}"):  # Version values holding the old ID (a deal's `contact`)
		frappe.db.set_value("Version", version, "data", frappe.as_json(fixed), update_modified=False)
frappe.db.delete("__global_search", {{"doctype": doctype, "name": old}})
base, _dash, suffix = old.rpartition("-")
for stem in {{f"{{old}}-", *([f"{{base}}-"] if base and suffix.isdigit() else [])}}:  # naming-series counters
	if not frappe.db.exists(doctype, {{"name": ("like", f"{{stem}}%")}}):
		frappe.db.sql("delete from `tabSeries` where name = %s", (stem,))
```
"""


def verification() -> list[str]:
	"""The residual check of crm.erasure.verify.full_scan, spelled out for a manual run"""
	email_sql, _values = column_conditions(COLUMN, STAND_IN_EMAIL)
	digits_sql, _values = column_conditions(COLUMN, STAND_IN_PHONE)
	token_sql, _values = column_conditions(COLUMN, Identifiers(), tokens=("stand-in",))
	return [
		"## Verify: nothing of hers is left",
		"",
		"With the feature installed, run the same check the product runs:",
		"",
		"```",
		"bench --site <site> execute crm.erasure.verify.full_scan_request --kwargs \"{'name': 'CRM-ERQ-...'}\"",
		"```",
		"",
		"For a manual run, the console runs the conditions `full_scan` runs (`verify.column_conditions`) on",
		"every text column of every table but the request's own: each address (whole address only), each",
		"number (digits only) and, as an extra check, her full name. First the conditions (`{column}` is",
		"filled in per column):",
		"",
		"```python",
		f"EMAIL_SQL = {email_sql!r}",
		f"DIGITS_SQL = {digits_sql!r}",
		f"TOKEN_SQL = {token_sql!r}",
		"```",
		"",
		"then the search:",
		"",
		"```python",
		"import re",
		f"BEFORE, AFTER = {_BEFORE!r}, {_AFTER!r}",
		f"ENCODINGS, ENCODED_BEFORE = {EMAIL_ENCODINGS!r}, {ENCODED_BEFORE!r}  # '@' written as %40 or &#64;",
		"",
		"",
		"def like(value):",
		'\treturn "%" + value.replace("\\\\", "\\\\\\\\").replace("%", r"\\%").replace("_", r"\\_") + "%"',
		"",
		"",
		"def email_values(email):",
		'\tspellings = [(email, BEFORE)] + [(email.replace("@", c), ENCODED_BEFORE) for c in ENCODINGS]',
		"\treturn [v for spelling, before in spellings for v in (like(spelling), before + re.escape(spelling) + AFTER)]",
		"",
		"",
		"searches = [(EMAIL_SQL, email_values(e)) for e in emails]",
		'searches += [(DIGITS_SQL, ["%" + d + "%"]) for d in phone_digits]',
		"searches += [(TOKEN_SQL, [like(n)]) for n in full_names]",
		"columns = frappe.db.sql(",
		'\t"select table_name, column_name from information_schema.columns "',
		'\t"where table_schema = database() and lower(data_type) in %(types)s and table_name not in %(skip)s "',
		'\t"and table_name in (select table_name from information_schema.tables "',
		"\t\"where table_schema = database() and table_type = 'BASE TABLE')\",",
		f'\t{{"types": {TEXT_TYPES!r}, "skip": {REQUEST_TABLES!r}}},',
		")",
		"left = set()",
		"for table, column in columns:",
		"\tfor condition, values in searches:",
		'\t\tif frappe.db.sql(f"select 1 from `{table}` where {condition.format(column=column)} limit 1", values):',
		"\t\t\tleft.add(table)",
		"print(sorted(left))",
		"```",
		"",
		"It must print `[]`. A table listed only because of rows you",
		"deliberately kept (a record that is not hers, or a namesake that only shares her name) passes; any",
		"other table means a step was missed: fix it and run the check again. Then `frappe.db.commit()`, and",
		"only then delete the File paths you noted from disk.",
		"",
	]
