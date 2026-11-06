# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
"""Runbook: the section of one registry entry (where to find it, what to change, the statements)

Statements mirror the executor: raw writes (`frappe.db.set_value(..., update_modified=False)`,
`frappe.db.delete`) so the erasure itself adds no Version, Deleted Document or `modified` change.
"""

from dataclasses import replace

from crm.erasure import registry_model as model
from crm.erasure.hidden_copies import EMAIL_QUEUE_BODY
from crm.erasure.runbook_finder_sql import entry_select, keys_placeholder

REQ = "<REQ>"  # the request number, or the Privacy team's case number when the feature is not installed
T = "\t"
_VALUES = {
	model.CLEAR: "None",
	model.MARKER: repr(model.content_marker(REQ)),
	model.NAME_MARKER: repr(model.name_marker(REQ)),
}
_TREATMENTS = {
	model.CLEAR: "clear it.",
	model.MARKER: f"set to `{model.content_marker(REQ)}`.",
	model.NAME_MARKER: f"set to `{model.name_marker(REQ)}`.",
	model.REMOVE_ADDRESS: "remove her addresses from the list, keep everyone else's; clear it when none is left.",
	model.CLEAR_IF_HERS: "clear it, only on rows where {} is hers.",
	model.MARKER_IF_HERS: f"set to `{model.name_marker(REQ)}`, only on rows where {{}} is hers.",
	model.DELETE_ROWS: "delete all its child rows.",
	model.DROP_HER_LINKS: "delete the link rows pointing at her Lead, Deal or Contact.",
}
_BY_HAND = (model.REMOVE_ADDRESS, model.CLEAR_IF_HERS, model.MARKER_IF_HERS)
_ACTIONS = {
	model.SCRUB: "Keep the record; change the fields below.",
	model.REPLACE_CONTENT: "Keep the row (dashboards count it); replace its content as below.",
	model.DELETE_PERMANENTLY: "Delete the row without a Deleted Document copy.",
	model.PURGE: "Delete the rows.",
	model.FILTER_ENTRIES: "Keep the row; drop the entries of its data that carry her data.",
	model.UNLINK: "Keep the record; delete only her link rows.",
	model.REWRITE_COMMENTS: "Rewrite the column, keeping only the `name` of each cached comment.",
}
# What crm/erasure/hidden_copies.py does beyond the registry rows
_EXTRA_FINDERS = {"Email Queue": (EMAIL_QUEUE_BODY,)}
_EXTRA_STEPS = {
	"Version": [
		"Versions found only by their `data` (not of a record found above) are filtered too. Filtering: "
		"edit `data`, dropping every change of a field listed in the sections above and every entry "
		"naming her identifiers; delete the Version when nothing is left. A Version whose `data` is not "
		"valid JSON is never deleted as empty: look at it by hand (the product keeps it and counts it "
		"under `skipped` in the outcome).",
	],
	"__global_search": [
		"Afterwards re-index each record found above: `update_global_search(frappe.get_doc(doctype, name))` "
		"per record, then `sync_global_search()` (both from `frappe.utils.global_search`).",
	],
	"Email Queue": ["Delete their Email Queue Recipient rows first (below)."],
}
_FILE_STEPS = [
	'Note each row\'s full path first: `frappe.get_doc("File", name).get_full_path()`.',
	'Delete the row raw, never with `delete_doc` (its `on_trash` adds an "Attachment Removed" comment naming the file).',
	"After `frappe.db.commit()`, delete the file on disk only when no other File row has the same `file_url`.",
	"With the feature installed the job does the same (rows in the transaction, disk files after the commit); "
	"disk files it could not delete are retried, also once the request is Closed, with "
	"`bench --site <site> execute crm.erasure.post_commit.finish_files --kwargs \"{'name': 'CRM-ERQ-...'}\"`.",
]


def entry_section(number: int, entry: model.Entry) -> list[str]:
	lines = [f"### {number}. {entry.doctype}", "", f"**Where:** {entry.found_by}.", ""]
	lines += [f"- {line}" for line in _where(entry)] + [""]
	lines += [f"**What to change:** {_ACTIONS[entry.action]}", ""]
	changes = _changes(entry)
	lines += [f"- {line}" for line in changes] + [""] if changes else []
	if entry.keep:
		lines += ["**Keep as they are:** " + ", ".join(f"`{field}`" for field in entry.keep) + ".", ""]
	statements = [*_find_statement(entry), *_change_statements(entry)]
	return [*lines, "**Console:**", "", "```python", *statements, "```", ""]


def _where(entry) -> list[str]:
	where = [f"Only when the `{entry.app}` app is installed; skip this step otherwise."] if entry.app else []
	searched = [f for f in entry.finders if hasattr(f, "columns")]
	if entry.table:
		where.append("Not a DocType: console only.")
	else:
		columns = [c for f in searched if not getattr(f, "child_doctype", None) for c in f.columns]
		desk = f"Desk: `/app/{entry.doctype.lower().replace(' ', '-')}`"
		where.append(desk + (", filter on " + _codes(columns) if columns else "") + ".")
	where += [
		f"Also its `{f.child_doctype}` rows: {_codes(f.columns)}."
		for f in searched
		if getattr(f, "child_doctype", None)
	]
	return where


def _changes(entry) -> list[str]:
	changes = [
		f"`{spec[0]}`: " + _TREATMENTS[spec[1]].format(*(f"`{c}`" for c in spec[2:])) for spec in entry.fields
	]
	if entry.shared_action == model.UNLINK:
		changes.append(
			"When the record also links to records that are not hers: delete only her link rows, change nothing else."
		)
	if entry.filter_doctypes:
		changes.append("Rows of " + ", ".join(entry.filter_doctypes) + " are filtered, not deleted (below).")
	if entry.action == model.DELETE_PERMANENTLY:
		changes += _FILE_STEPS
	return changes + _EXTRA_STEPS.get(entry.doctype, [])


def _find_statement(entry) -> list[str]:
	if entry.action == model.REWRITE_COMMENTS:
		return ["# her records found above, and the records her Comments and Communications sit on"]
	select = entry_select(replace(entry, finders=entry.finders + _EXTRA_FINDERS.get(entry.doctype, ())))
	if select is None and {"link_doctype", "link_name"} <= set(entry.keep):
		params: dict[str, str] = {}
		key = keys_placeholder(model.SUBJECTS, params)
		select = (
			f"select `name` from `tab{entry.doctype}`\nwhere concat(`link_doctype`, '::', `link_name`) in {key}",
			params,
		)
	if select is None:
		return ["# no search of its own: the rows come from the records found above"]
	sql, params = select
	args = ", {" + ", ".join(f'"{k}": {v}' for k, v in params.items()) + "}" if params else ""
	return [f'find("{entry.doctype}", """', *sql.splitlines(), f'"""{args})']


def _change_statements(entry) -> list[str]:
	target = f'found["{entry.doctype}"]'
	if entry.action == model.REWRITE_COMMENTS:
		return _rewrite_comments()
	if entry.filter_doctypes:
		return [
			f"for name in {target}:",
			f'{T}ref = frappe.db.get_value("{entry.doctype}", name, ["ref_doctype", "docname"], as_dict=True)',
			f'{T}if ref.ref_doctype in {entry.filter_doctypes!r} or f"{{ref.ref_doctype}}::{{ref.docname}}" not in keys():',
			f"{T}{T}continue  # filter its `data` by hand (above)",
			f'{T}frappe.db.delete("{entry.doctype}", name)',
		]
	if entry.action == model.PURGE and entry.table:
		sql = f"delete from `{entry.table}` where concat(`doctype`, '::', `name`) in %(keys)s"
		return [f'frappe.db.sql("{sql}", {{"keys": tuple({target}) or ("",)}})']
	if entry.doctype == "Email Queue":
		parents = f'{{"parenttype": "Email Queue", "parent": ("in", {target})}}'
		return [
			f'frappe.db.delete("Email Queue Recipient", {parents})',
			f'frappe.db.delete("Email Queue", {{"name": ("in", {target})}})',
		]
	if entry.action in (model.PURGE, model.DELETE_PERMANENTLY):
		return [f'frappe.db.delete("{entry.doctype}", {{"name": ("in", {target})}})']
	return _field_writes(entry, target)


def _field_writes(entry, target: str) -> list[str]:
	lines = [f"for name in {target}:"]
	plain = ", ".join(f'"{spec[0]}": {_VALUES[spec[1]]}' for spec in entry.fields if spec[1] in _VALUES)
	shared = entry.shared_action == model.UNLINK
	if shared:
		lines.insert(0, "shared = []  # rows that also link to records that are not hers: fill in by hand")
	if plain:
		write = f'frappe.db.set_value("{entry.doctype}", name, {{{plain}}}, update_modified=False)'
		lines += [f"{T}if name not in shared:", f"{T}{T}{write}"] if shared else [f"{T}{write}"]
	for spec in entry.fields:
		if spec[1] not in (model.DELETE_ROWS, model.DROP_HER_LINKS):
			continue
		child = f'frappe.get_meta("{entry.doctype}").get_field("{spec[0]}").options'
		her_links = ', "link_name": ("in", names("CRM Lead") + names("CRM Deal") + names("Contact"))'
		extra = her_links if spec[1] == model.DROP_HER_LINKS else ""
		lines.append(
			f'{T}frappe.db.delete({child}, {{"parenttype": "{entry.doctype}", "parent": name, "parentfield": "{spec[0]}"{extra}}})'
		)
	if any(spec[1] in _BY_HAND for spec in entry.fields):
		lines.append(f"{T}# then, row by row, the fields above that depend on whose value it is")
	return lines if any(line.startswith(T) for line in lines) else []


def _rewrite_comments() -> list[str]:
	return [
		'targets = {tuple(key.split("::", 1)) for key in keys()}',
		'for doctype in ("Comment", "Communication"):',
		f'{T}rows = frappe.get_all(doctype, {{"name": ("in", names(doctype))}}, ["reference_doctype", "reference_name"])',
		f"{T}targets |= {{(r.reference_doctype, r.reference_name) for r in rows if r.reference_name}}",
		"for doctype, name in sorted(targets):",
		f'{T}if frappe.get_meta(doctype).istable or doctype == "CRM Erasure Request":',
		f"{T}{T}continue",
		f'{T}stored = frappe.db.get_value(doctype, name, "_comments")',
		f"{T}if stored:",
		f'{T}{T}kept = [{{"name": e["name"]}} for e in json.loads(stored) if isinstance(e, dict) and e.get("name")]',
		f'{T}{T}frappe.db.set_value(doctype, name, "_comments", json.dumps(kept), update_modified=False)',
	]


def _codes(names) -> str:
	return ", ".join(f"`{name}`" for name in names)
