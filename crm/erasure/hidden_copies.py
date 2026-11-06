# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
"""Hidden copies of her data: Version, Deleted Document, global search, Email Queue, logs, `_comments`

Rows are found with discovery's own finders (`discovery_queries.find`) over the request's
non-excluded matches, so execution purges what the preview counted. Rows of excluded matches and
of the request itself are never touched. All writes are raw (`frappe.db.*`).
"""

import json
import re

import frappe

from crm.erasure import registry_model as model
from crm.erasure.discovery_queries import find
from crm.erasure.registry import PERSON_FIELDS
from crm.erasure.scrub_actions import filter_version_data, version_is_empty
from crm.erasure.verify import encoded_email_patterns

REQUEST = "CRM Erasure Request"
# Queued mail may carry her address in the MIME body only (no recipient row is hers)
EMAIL_QUEUE_BODY = model.Text(("message",))


def purge_versions(ctx, entry: model.Entry, changes) -> None:
	"""Versions of matches are deleted (CRM Deal: filtered); other Versions naming her are filtered"""
	handled = set()
	for doctype, names in sorted(ctx.matches.items()):
		rows = frappe.get_all("Version", {"ref_doctype": doctype, "docname": ["in", sorted(names)]}, ["name", "data"])
		for row in rows:
			handled.add(row.name)
			if doctype in entry.filter_doctypes:
				_filter_version(ctx, row, PERSON_FIELDS.get(doctype, frozenset()), changes)
			else:
				frappe.db.delete("Version", row.name)
				changes.add("Version")
	for name in sorted(find(entry, _text_finder(entry), {}, ctx.ids) - handled):
		row = frappe.db.get_value("Version", name, ["name", "ref_doctype", "docname", "data"], as_dict=True)
		if row and row.ref_doctype != REQUEST and (row.ref_doctype, row.docname) not in ctx.excluded:
			_filter_version(ctx, row, frozenset(), changes)


def purge_deleted_documents(ctx, entry: model.Entry, changes) -> None:
	_delete_rows("Deleted Document", _found(ctx, entry) | _encoded_hits(ctx, entry), changes)


def purge_search_rows(ctx, entry: model.Entry, changes) -> None:
	"""Search rows of matches and rows whose content names her; matches are re-indexed after commit

	A match's row that carries the marker was re-indexed after the erasure, so a re-run leaves it;
	a shared record (unlink only: nothing of hers is indexed on it) keeps its row.
	"""
	allowed = lambda key: key not in ctx.excluded and key[0] != REQUEST  # noqa: E731
	naming_her = {tuple(key.split("::", 1)) for key in find(entry, _text_finder(entry), {}, ctx.ids)}
	markers = (model.content_marker(ctx.request_name), model.name_marker(ctx.request_name))
	for doctype, names in sorted(ctx.matches.items()):
		for name in sorted(names):
			key = (doctype, name)
			shared = ctx.actions.get(key) == model.UNLINK
			if key not in naming_her and not shared and allowed(key) and _unmarked_search_row(key, markers):
				naming_her.add(key)
	for doctype, name in sorted(filter(allowed, naming_her)):
		frappe.db.delete("__global_search", {"doctype": doctype, "name": name})
		changes.add("__global_search")
	for doctype, names in sorted(ctx.matches.items()):
		if frappe.get_meta(doctype).get_global_search_fields():
			changes.reindex.extend((doctype, name) for name in sorted(names))


def purge_email_queue(ctx, entry: model.Entry, changes) -> None:
	names = _found(ctx, entry) | find(entry, EMAIL_QUEUE_BODY, {}, ctx.ids)
	if names:
		frappe.db.delete("Email Queue Recipient", {"parenttype": "Email Queue", "parent": ["in", sorted(names)]})
	_delete_rows("Email Queue", names, changes)


def purge_logs(ctx, entry: model.Entry, changes) -> None:
	_delete_rows(entry.doctype, _found(ctx, entry) | _encoded_hits(ctx, entry), changes)


def rewrite_comments_column(ctx, entry: model.Entry, changes) -> None:
	"""`_comments` of her records and of records her comments or emails sit on: `{name}` entries only"""
	targets = {(doctype, name) for doctype, names in ctx.matches.items() for name in names}
	for doctype in ("Comment", "Communication"):
		names = sorted(ctx.matches.get(doctype, ()))
		if names:
			rows = frappe.get_all(doctype, {"name": ["in", names]}, ["reference_doctype", "reference_name"])
			targets |= {(row.reference_doctype, row.reference_name) for row in rows if row.reference_name}
	for doctype, name in sorted(targets - ctx.excluded):
		meta = frappe.get_meta(doctype)
		if meta.istable or doctype == REQUEST:
			continue
		stored = frappe.db.get_value(doctype, name, "_comments")
		if stored is None:
			continue
		rewritten = json.dumps(_name_only(stored))
		if rewritten != stored:
			frappe.db.set_value(doctype, name, "_comments", rewritten, update_modified=False)
			changes.add("_comments")


HANDLERS = {
	"Version": purge_versions,
	"Deleted Document": purge_deleted_documents,
	"__global_search": purge_search_rows,
	"Email Queue": purge_email_queue,
	"WA Log": purge_logs,
	"Error Log": purge_logs,
	"_comments": rewrite_comments_column,
}


def _text_finder(entry: model.Entry) -> model.Text:
	return next(finder for finder in entry.finders if isinstance(finder, model.Text))


def _found(ctx, entry: model.Entry) -> set[str]:
	matched = ctx.as_matched()
	return set().union(*(find(entry, finder, matched, ctx.ids) for finder in entry.finders))


def _encoded_hits(ctx, entry: model.Entry) -> set[str]:
	"""Rows whose text columns hold her address with "@" encoded (%40, &#64;): logs and payloads"""
	patterns = [p for email in sorted(ctx.ids.emails) for p in encoded_email_patterns(email)]
	columns = _text_finder(entry).columns
	if not patterns:
		return set()
	conditions = " or ".join(f"lower(`{column}`) like %s" for column in columns for _p in patterns)
	values = [f"%{spelling}%" for _column in columns for spelling, _regex in patterns]
	selected = ", ".join(f"`{column}`" for column in columns)
	rows = frappe.db.sql(f"select name, {selected} from `tab{entry.doctype}` where {conditions}", values, as_dict=True)
	regexes = [re.compile(regex) for _spelling, regex in patterns]
	return {row.name for row in rows if any(r.search(str(row[c] or "").lower()) for r in regexes for c in columns)}


def _delete_rows(doctype: str, names, changes) -> None:
	names = sorted(names)
	if names:
		frappe.db.delete(doctype, {"name": ["in", names]})
		changes.add(doctype, len(names))


def _unmarked_search_row(key: tuple[str, str], markers: tuple[str, str]) -> bool:
	return bool(
		frappe.db.sql(
			"select 1 from `__global_search` where doctype = %s and name = %s "
			"and content not like %s and content not like %s limit 1",
			(*key, f"%{markers[0]}%", f"%{markers[1]}%"),
		)
	)


def _filter_version(ctx, row, person_fields, changes) -> None:
	try:
		data = json.loads(row.data or "{}")
	except ValueError:
		changes.skipped["Version"] += 1  # unreadable: never deleted as "empty", left for a person to look at
		return
	kept = filter_version_data(data, person_fields, ctx.ids, ctx.her_rows)
	if version_is_empty(kept) or ctx.ids.matches_text(json.dumps(kept, default=str)):
		frappe.db.delete("Version", row.name)
		changes.add("Version")
	elif kept != data:
		frappe.db.set_value("Version", row.name, "data", frappe.as_json(kept), update_modified=False)
		changes.add("Version")


def _name_only(stored: str) -> list[dict]:
	try:
		entries = json.loads(stored or "[]")
	except ValueError:
		return []
	if not isinstance(entries, list):
		return []
	return [{"name": e["name"]} for e in entries if isinstance(e, dict) and e.get("name")]
