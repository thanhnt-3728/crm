# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
"""Discovery: walk the registry for one request and return match rows (doc names only)

Read-only. Order of work: the request's source, then her person records resolved together until
nothing new turns up (a lead leads to its deals, a deal to its lead, a contact to its deals),
then every other entry once in registry order, then hidden copies as counts. A record is never
matched by name alone: only by a link to her records or by one of her emails or phones.

Matches the request marks excluded are still found and listed (so their flag survives), but
nothing is reached through them: a comment found only through an excluded email thread drops out.
"""

from collections import defaultdict
from dataclasses import dataclass, field

import frappe

from crm.erasure import registry_model as model
from crm.erasure.discovery_queries import Matched, find
from crm.erasure.identifiers import Identifiers
from crm.erasure.match_rows import diff_matches, hand_excluded
from crm.erasure.registry import REGISTRY, registry_position

__all__ = ["Discovery", "diff_matches", "discover", "excluded_keys", "hidden_counts", "installed"]

SUBJECT_ENTRY_DOCTYPES = ("CRM Lead", "CRM Deal", "CRM Contacts", "Contact")
LINKED, ACTIVITY, EMAIL, PHONE = "linked", "activity", "email", "phone"
REASON_PRIORITY = (LINKED, ACTIVITY, EMAIL, PHONE)


@dataclass
class Discovery:
	matches: list[dict] = field(default_factory=list)  # {ref_doctype, ref_name, reason, action}
	hidden: dict[str, int] = field(default_factory=dict)  # hidden-copy doctype -> row count


def discover(request, excluded: set[tuple[str, str]] | None = None) -> Discovery:
	"""Match rows for `request` (its source, identifiers and exclusions), in registry order

	`excluded`: keys not to traverse through; default the rows excluded by hand
	(`set()` = ignore exclusions, i.e. everything reachable). Raises ValueError when a stored identifier no longer normalizes (callers turn it into a
	ValidationError without the value).
	"""
	ids = Identifiers.from_rows(request.get("identifiers") or [])
	excluded = hand_excluded(request.get("matches") or []) if excluded is None else excluded
	entries = [entry for entry in REGISTRY if installed(entry)]
	matched = _seed(request)
	_resolve_subjects([e for e in entries if e.doctype in SUBJECT_ENTRY_DOCTYPES], matched, ids, excluded)
	for entry in entries:
		if entry.doctype not in SUBJECT_ENTRY_DOCTYPES and entry.match_rows and entry.kind != model.HIDDEN:
			_collect(entry, entry.finders, matched, ids, excluded)
	hidden = _count_hidden(entries, matched, ids, excluded)
	return Discovery(matches=_rows(entries, matched), hidden=hidden)


def hidden_counts(request) -> dict[str, int]:
	"""Hidden-copy counts for the request's stored, non-excluded matches"""
	ids = Identifiers.from_rows(request.get("identifiers") or [])
	matched = _seed(request)
	for row in request.get("matches") or []:
		if not row.get("excluded"):
			matched[row.get("ref_doctype")].setdefault(row.get("ref_name"), row.get("reason") or LINKED)
	return _count_hidden([entry for entry in REGISTRY if installed(entry)], matched, ids, set())


def excluded_keys(request) -> set[tuple[str, str]]:
	return {
		(r.get("ref_doctype"), r.get("ref_name")) for r in request.get("matches") or [] if r.get("excluded")
	}


def installed(entry: model.Entry) -> bool:
	"""False for entries of an optional app that is not installed on this site"""
	return not entry.app or entry.app in frappe.get_installed_apps()


def _resolve_subjects(subjects, matched: Matched, ids: Identifiers, excluded) -> None:
	"""Fixed point over the subject entries, re-running only finders whose targets just grew"""
	pending = [(entry, finder) for entry in subjects for finder in entry.finders]
	while pending:  # terminates: the matched set only grows and is bounded by the database
		before = {doctype: len(names) for doctype, names in matched.items()}
		for entry, finder in pending:
			_collect(entry, (finder,), matched, ids, excluded)
		grown = {doctype for doctype, names in matched.items() if len(names) > before.get(doctype, 0)}
		pending = [(e, f) for e in subjects for f in e.finders if grown & _depends_on(f, grown)]


def _depends_on(finder, grown: set[str]) -> set[str]:
	"""Doctypes whose matches `finder` reads (identifier finders read none)"""
	if isinstance(finder, model.Ref | model.ChildLink):
		return grown if finder.targets == model.ANY_MATCH else set(finder.targets)
	if isinstance(finder, model.Link):
		return {finder.target}
	if isinstance(finder, model.Backref | model.ChildBackref):
		return {finder.source}
	return set()


def _collect(entry: model.Entry, finders, matched: Matched, ids: Identifiers, excluded) -> None:
	reachable = _traversable(matched, excluded)
	found = matched[entry.doctype]
	for finder in finders:
		reason = _reason(entry, finder)
		for name in find(entry, finder, reachable, ids):
			if name not in found or REASON_PRIORITY.index(reason) < REASON_PRIORITY.index(found[name]):
				found[name] = reason


def _traversable(matched: Matched, excluded) -> Matched:
	"""The matches other records may be reached through: all but the excluded ones"""
	if not excluded:
		return matched
	return {
		doctype: {name: reason for name, reason in names.items() if (doctype, name) not in excluded}
		for doctype, names in matched.items()
	}


def _reason(entry: model.Entry, finder) -> str:
	if isinstance(finder, model.Emails):
		return EMAIL
	if isinstance(finder, model.Phones):
		return PHONE
	return ACTIVITY if entry.kind == model.ACTIVITY else LINKED


def _rows(entries: list[model.Entry], matched: Matched) -> list[dict]:
	rows = []
	for entry in entries:
		if not entry.match_rows or entry.kind == model.HIDDEN:
			continue
		shared = _shared_rows(entry, matched)
		for name, reason in matched.get(entry.doctype, {}).items():
			action = entry.shared_action if name in shared else entry.action
			rows.append({"ref_doctype": entry.doctype, "ref_name": name, "reason": reason, "action": action})
	return sorted(rows, key=lambda row: (registry_position(row["ref_doctype"]), row["ref_name"]))


def _shared_rows(entry: model.Entry, matched: Matched) -> set[str]:
	"""Names of `entry` rows that also link to records outside her matches (e.g. a shared Address)"""
	finder = next((f for f in entry.finders if isinstance(f, model.ChildLink)), None)
	names = sorted(matched.get(entry.doctype, ()))
	if not entry.shared_action or not finder or not names:
		return set()
	links = frappe.get_all(
		finder.child_doctype,
		filters={"parenttype": entry.doctype, "parent": ["in", names]},
		fields=["parent", "link_doctype", "link_name"],
	)
	return {link.parent for link in links if link.link_name not in matched.get(link.link_doctype, {})}


def _seed(request) -> Matched:
	matched: Matched = defaultdict(dict)
	if request.source_docname and frappe.db.exists(request.source_doctype, request.source_docname):
		matched[request.source_doctype][request.source_docname] = LINKED
	return matched


def _count_hidden(entries, matched: Matched, ids: Identifiers, excluded) -> dict[str, int]:
	reachable = _traversable(matched, excluded)
	return {
		entry.doctype: len(set().union(*(find(entry, finder, reachable, ids) for finder in entry.finders)))
		for entry in entries
		if entry.kind == model.HIDDEN and entry.finders
	}
